"""
Tests for CDLI MCP Server tools.
Validates tool registration, input validation, mock fallback behavior,
and structured error responses.
"""

import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from cdli_mcp import (
    list_tools,
    handle_search,
    handle_metadata,
    handle_export,
    _mock_search,
    _mock_metadata,
)


# ── Tool Registration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tools_returns_all_tools():
    """Server should register exactly 3 tools."""
    tools = await list_tools()
    names = [t.name for t in tools]
    assert len(tools) == 3
    assert "search_artifacts" in names
    assert "get_artifact_metadata" in names
    assert "export_artifacts" in names


@pytest.mark.asyncio
async def test_tools_have_input_schemas():
    """Every tool should have a valid JSON input schema."""
    tools = await list_tools()
    for tool in tools:
        assert tool.inputSchema is not None
        assert "properties" in tool.inputSchema


# ── Search Tool ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_mock_on_connection_error():
    """When CDLI API is unreachable, search should return mock data flagged as 'mock'."""
    result = await handle_search({"query": "beer rations"})
    data = json.loads(result[0].text)
    assert data["source"] == "mock"
    assert "results" in data["data"]
    assert len(data["data"]["results"]) > 0


@pytest.mark.asyncio
async def test_search_invalid_input():
    """Missing required 'query' field should return INVALID_INPUT error."""
    result = await handle_search({})
    data = json.loads(result[0].text)
    assert data["error_code"] == "INVALID_INPUT"
    assert data["suggested_action"] == "reformulate"


@pytest.mark.asyncio
async def test_search_with_filters():
    """Search should accept optional period and location filters."""
    result = await handle_search({
        "query": "administrative tablet",
        "period": "Ur III",
        "location": "Girsu",
        "page": 1,
        "page_size": 5,
    })
    data = json.loads(result[0].text)
    # Should succeed (mock or live)
    assert "data" in data


# ── Metadata Tool ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metadata_single_artifact():
    """Single artifact fetch should return results."""
    result = await handle_metadata({"artifact_id": "P000001"})
    data = json.loads(result[0].text)
    assert "data" in data
    assert data["data"]["total"] == 1
    assert data["data"]["results"][0]["id"] == "P000001"


@pytest.mark.asyncio
async def test_metadata_batch_artifacts():
    """Batch fetch should return results for all requested IDs."""
    ids = ["P000001", "P000002", "P000003"]
    result = await handle_metadata({"artifact_ids": ids})
    data = json.loads(result[0].text)
    assert data["data"]["total"] == 3


@pytest.mark.asyncio
async def test_metadata_no_id_provided():
    """Providing neither artifact_id nor artifact_ids should return error."""
    result = await handle_metadata({})
    data = json.loads(result[0].text)
    assert data["error_code"] == "INVALID_INPUT"


# ── Export Tool ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_json_format():
    """Export in JSON format should return structured artifact data."""
    result = await handle_export({
        "artifact_ids": ["P000001"],
        "format": "json",
    })
    data = json.loads(result[0].text)
    assert data["data"]["format"] == "json"
    assert data["data"]["count"] == 1
    assert "citation" in data["data"]["artifacts"][0]


@pytest.mark.asyncio
async def test_export_csv_format():
    """Export in CSV format should return CSV string with headers."""
    result = await handle_export({
        "artifact_ids": ["P000001"],
        "format": "csv",
    })
    data = json.loads(result[0].text)
    assert data["data"]["format"] == "csv"
    assert "content" in data["data"]
    lines = data["data"]["content"].split("\n")
    assert len(lines) >= 2  # header + at least 1 row


@pytest.mark.asyncio
async def test_export_selected_fields():
    """Export with field selection should only include requested fields."""
    result = await handle_export({
        "artifact_ids": ["P000001"],
        "format": "json",
        "fields": ["id", "period"],
    })
    data = json.loads(result[0].text)
    artifact = data["data"]["artifacts"][0]
    assert "id" in artifact
    assert "period" in artifact
    # transliteration should not be present (not selected)
    assert "transliteration" not in artifact


# ── Mock Data ────────────────────────────────────────────────────────────────

def test_mock_search_structure():
    """Mock search should return properly structured data."""
    data = _mock_search("test", 1, 10)
    assert "results" in data
    assert "total_count" in data
    assert "next_page_token" in data
    for item in data["results"]:
        assert "id" in item
        assert "period" in item
        assert "provenance" in item


def test_mock_metadata_structure():
    """Mock metadata should return all expected fields."""
    data = _mock_metadata("P000001")
    assert data["id"] == "P000001"
    assert "period" in data
    assert "transliteration" in data
    assert "bibliography" in data
    assert isinstance(data["bibliography"], list)


# ── Error Response Format ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_responses_are_valid_json():
    """All error responses should be parseable JSON with required fields."""
    result = await handle_search({})  # triggers INVALID_INPUT
    data = json.loads(result[0].text)
    assert "error_code" in data
    assert "message" in data
    assert "suggested_action" in data

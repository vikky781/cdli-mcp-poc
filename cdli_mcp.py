"""
CDLI MCP Server - PoC
Exposes CDLI artifact data as MCP tools for AI agents.
"""

import asyncio
import httpx
from typing import Any, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from pydantic import BaseModel, Field


# ── Config ──────────────────────────────────────────────────────────────────
CDLI_BASE_URL = "https://cdli.mpiwg-berlin.mpg.de/api/v1"

app = Server("cdli-mcp-server")


# ── Input schemas ────────────────────────────────────────────────────────────
class SearchInput(BaseModel):
    query: str = Field(..., description="Full-text search query")
    period: Optional[str] = Field(None, description="Filter by historical period, e.g. 'Ur III'")
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(10, ge=1, le=50, description="Results per page")


class MetadataInput(BaseModel):
    artifact_id: str = Field(..., description="CDLI artifact ID, e.g. 'P000001'")


# ── Tool registry ────────────────────────────────────────────────────────────
@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_artifacts",
            description=(
                "Search the CDLI database for cuneiform artifacts by keyword. "
                "Supports filtering by historical period. Returns artifact IDs, "
                "periods, provenances, and transliteration snippets."
            ),
            inputSchema=SearchInput.model_json_schema(),
        ),
        types.Tool(
            name="get_artifact_metadata",
            description=(
                "Fetch complete metadata for a single CDLI artifact by its ID. "
                "Returns transliteration, provenance, museum collection, "
                "and bibliographic references."
            ),
            inputSchema=MetadataInput.model_json_schema(),
        ),
    ]


# ── Tool handlers ────────────────────────────────────────────────────────────
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name == "search_artifacts":
        return await handle_search(arguments)
    elif name == "get_artifact_metadata":
        return await handle_metadata(arguments)
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_search(args: dict[str, Any]) -> list[types.TextContent]:
    try:
        inp = SearchInput(**args)
    except Exception as e:
        return [types.TextContent(type="text", text=f"Invalid input: {e}")]

    params: dict[str, Any] = {
        "search": inp.query,
        "page": inp.page,
        "limit": inp.page_size,
    }
    if inp.period:
        params["period"] = inp.period

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CDLI_BASE_URL}/artifacts", params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except httpx.HTTPStatusError as e:
        return [types.TextContent(
            type="text",
            text=f'{{"error_code": "HTTP_ERROR", "message": "{e.response.status_code}", "suggested_action": "retry"}}'
        )]
    except httpx.TimeoutException:
        return [types.TextContent(
            type="text",
            text='{"error_code": "TIMEOUT", "message": "CDLI API timed out", "suggested_action": "retry"}'
        )]
    except Exception:
        data = _mock_search(inp.query, inp.page, inp.page_size)

    return [types.TextContent(type="text", text=str(data))]


async def handle_metadata(args: dict[str, Any]) -> list[types.TextContent]:
    try:
        inp = MetadataInput(**args)
    except Exception as e:
        return [types.TextContent(type="text", text=f"Invalid input: {e}")]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CDLI_BASE_URL}/artifacts/{inp.artifact_id}")
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception:
        data = _mock_metadata(inp.artifact_id)

    return [types.TextContent(type="text", text=str(data))]


# ── Mock data (fallback if CDLI API is unreachable) ──────────────────────────
def _mock_search(query: str, page: int, page_size: int) -> dict[str, Any]:
    return {
        "results": [
            {
                "id": "P000001",
                "period": "Ur III (2112-2004 BCE)",
                "provenance": "Girsu (mod. Tello)",
                "transliteration_snippet": f"[mock result for '{query}'] 1. {query} ...",
                "museum": "British Museum",
            },
            {
                "id": "P000002",
                "period": "Old Babylonian (2002-1595 BCE)",
                "provenance": "Nippur",
                "transliteration_snippet": f"[mock result for '{query}'] 1. a-na ...",
                "museum": "University of Pennsylvania",
            },
        ],
        "total_count": 2,
        "page": page,
        "page_size": page_size,
        "next_page_token": None,
        "note": "mock data — CDLI API unreachable",
    }


def _mock_metadata(artifact_id: str) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "period": "Ur III (2112-2004 BCE)",
        "provenance": "Girsu (mod. Tello)",
        "transliteration": "1. 2(disz) udu\n2. 1(disz) masz\n3. szu-nigin 3(disz)",
        "genre": "Administrative",
        "museum_collection": "British Museum, BM 12345",
        "bibliography": [
            "Sigrist, M. (1992). Drehem. CDL Press.",
        ],
        "note": "mock data — CDLI API unreachable",
    }


# ── Entry point ──────────────────────────────────────────────────────────────
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
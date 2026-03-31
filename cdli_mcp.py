"""
CDLI MCP Server — PoC
Exposes CDLI cuneiform artifact data as MCP tools for AI agents.
Built as a proof-of-concept for GSoC 2026 proposal.

Architecture:
  Transport  → stdio (MCP standard)
  Registry   → typed tool definitions with Pydantic schemas
  Adapter    → async HTTP client wrapping CDLI REST API
"""

import os
import asyncio
import json
import httpx
from typing import Any, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from pydantic import BaseModel, Field

# ── Config ──────────────────────────────────────────────────────────────────
CDLI_BASE_URL = os.environ.get("CDLI_BASE_URL", "https://cdli.mpiwg-berlin.mpg.de/api/v1")
CDLI_API_KEY = os.environ.get("CDLI_API_KEY", "")
REQUEST_TIMEOUT = float(os.environ.get("CDLI_TIMEOUT", "15.0"))
MAX_BATCH_SIZE = int(os.environ.get("CDLI_MAX_BATCH", "20"))

app = Server("cdli-mcp-server")


# ── Input schemas ────────────────────────────────────────────────────────────
class SearchInput(BaseModel):
    query: str = Field(..., description="Full-text search query")
    period: Optional[str] = Field(None, description="Filter by historical period, e.g. 'Ur III'")
    location: Optional[str] = Field(None, description="Filter by provenance/location, e.g. 'Girsu'")
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(10, ge=1, le=50, description="Results per page")


class MetadataInput(BaseModel):
    artifact_id: Optional[str] = Field(None, description="Single CDLI artifact ID, e.g. 'P000001'")
    artifact_ids: Optional[list[str]] = Field(None, description="List of CDLI artifact IDs for batch fetch")

    def get_ids(self) -> list[str]:
        """Return list of IDs whether single or batch was provided."""
        if self.artifact_ids:
            return self.artifact_ids[:MAX_BATCH_SIZE]
        if self.artifact_id:
            return [self.artifact_id]
        return []


class ExportInput(BaseModel):
    artifact_ids: list[str] = Field(..., description="List of CDLI artifact IDs to export")
    format: str = Field("json", description="Export format: 'json' or 'csv'")
    fields: Optional[list[str]] = Field(
        None,
        description="Fields to include. Defaults to all. Options: id, period, provenance, transliteration, genre, museum_collection, bibliography"
    )


# ── Structured error helpers ─────────────────────────────────────────────────
def _error_response(error_code: str, message: str, suggested_action: str, retry_after: Optional[int] = None) -> str:
    """Build a structured error response as JSON string."""
    err: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "suggested_action": suggested_action,
    }
    if retry_after is not None:
        err["retry_after"] = retry_after
    return json.dumps(err)


def _success_response(data: Any, source: str = "live") -> str:
    """Wrap a successful response with source metadata."""
    return json.dumps({"source": source, "data": data}, indent=2, default=str)


# ── Tool registry ────────────────────────────────────────────────────────────
@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_artifacts",
            description=(
                "Search the CDLI database for cuneiform artifacts by keyword. "
                "Supports filtering by historical period and location. Returns "
                "artifact IDs, periods, provenances, and transliteration snippets."
            ),
            inputSchema=SearchInput.model_json_schema(),
        ),
        types.Tool(
            name="get_artifact_metadata",
            description=(
                "Fetch complete metadata for one or more CDLI artifacts by ID. "
                "Supports batch requests (up to 20 IDs). Returns transliteration, "
                "provenance, museum collection, and bibliographic references."
            ),
            inputSchema=MetadataInput.model_json_schema(),
        ),
        types.Tool(
            name="export_artifacts",
            description=(
                "Export artifact data as JSON or CSV with selectable fields "
                "and citation-ready formatting."
            ),
            inputSchema=ExportInput.model_json_schema(),
        ),
    ]


# ── Tool dispatcher ──────────────────────────────────────────────────────────
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    handlers = {
        "search_artifacts": handle_search,
        "get_artifact_metadata": handle_metadata,
        "export_artifacts": handle_export,
    }
    handler = handlers.get(name)
    if not handler:
        return [types.TextContent(
            type="text",
            text=_error_response("UNKNOWN_TOOL", f"Tool '{name}' not found", "reformulate"),
        )]
    return await handler(arguments)


# ── Tool handlers ────────────────────────────────────────────────────────────
async def handle_search(args: dict[str, Any]) -> list[types.TextContent]:
    try:
        inp = SearchInput(**args)
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=_error_response("INVALID_INPUT", str(e), "reformulate"),
        )]

    params: dict[str, Any] = {
        "search": inp.query,
        "page": inp.page,
        "limit": inp.page_size,
    }
    if inp.period:
        params["period"] = inp.period
    if inp.location:
        params["location"] = inp.location

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(f"{CDLI_BASE_URL}/artifacts", params=params)

            # Rate limit handling
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "30"))
                return [types.TextContent(
                    type="text",
                    text=_error_response("RATE_LIMITED", "CDLI API rate limit reached", "retry", retry_after),
                )]

            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return [types.TextContent(type="text", text=_success_response(data, source="live"))]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(
            type="text",
            text=_error_response("HTTP_ERROR", f"CDLI returned status {e.response.status_code}", "retry"),
        )]
    except httpx.TimeoutException:
        return [types.TextContent(
            type="text",
            text=_error_response("TIMEOUT", "CDLI API request timed out", "retry"),
        )]
    except httpx.ConnectError:
        # API unreachable — return mock data clearly flagged
        data = _mock_search(inp.query, inp.page, inp.page_size)
        return [types.TextContent(type="text", text=_success_response(data, source="mock"))]
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=_error_response("INTERNAL_ERROR", str(e), "escalate"),
        )]


async def handle_metadata(args: dict[str, Any]) -> list[types.TextContent]:
    try:
        inp = MetadataInput(**args)
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=_error_response("INVALID_INPUT", str(e), "reformulate"),
        )]

    ids = inp.get_ids()
    if not ids:
        return [types.TextContent(
            type="text",
            text=_error_response("INVALID_INPUT", "Provide artifact_id or artifact_ids", "reformulate"),
        )]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    source = "live"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for artifact_id in ids:
                try:
                    resp = await client.get(f"{CDLI_BASE_URL}/artifacts/{artifact_id}")

                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", "30"))
                        return [types.TextContent(
                            type="text",
                            text=_error_response("RATE_LIMITED", "CDLI API rate limit reached", "retry", retry_after),
                        )]

                    resp.raise_for_status()
                    results.append(resp.json())
                except httpx.HTTPStatusError as e:
                    errors.append({"id": artifact_id, "status": e.response.status_code})
                except Exception:
                    errors.append({"id": artifact_id, "error": "fetch_failed"})

    except httpx.ConnectError:
        # API unreachable — return mock data clearly flagged
        source = "mock"
        results = [_mock_metadata(aid) for aid in ids]
        errors = []
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=_error_response("INTERNAL_ERROR", str(e), "escalate"),
        )]

    output = {"results": results, "total": len(results)}
    if errors:
        output["errors"] = errors

    return [types.TextContent(type="text", text=_success_response(output, source=source))]


async def handle_export(args: dict[str, Any]) -> list[types.TextContent]:
    try:
        inp = ExportInput(**args)
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=_error_response("INVALID_INPUT", str(e), "reformulate"),
        )]

    if len(inp.artifact_ids) > MAX_BATCH_SIZE:
        return [types.TextContent(
            type="text",
            text=_error_response("INVALID_INPUT", f"Maximum {MAX_BATCH_SIZE} artifacts per export", "reformulate"),
        )]

    # Fetch all artifact metadata first
    meta_result = await handle_metadata({"artifact_ids": inp.artifact_ids})
    meta_data = json.loads(meta_result[0].text)

    if "error_code" in meta_data:
        return meta_result  # propagate error

    all_fields = ["id", "period", "provenance", "transliteration", "genre", "museum_collection", "bibliography"]
    selected = inp.fields if inp.fields else all_fields
    artifacts = meta_data.get("data", {}).get("results", [])

    # Filter fields
    filtered = []
    for artifact in artifacts:
        row = {k: artifact.get(k, "") for k in selected if k in all_fields}
        # Add citation metadata
        row["citation"] = f"CDLI {artifact.get('id', 'unknown')} — https://cdli.mpiwg-berlin.mpg.de/{artifact.get('id', '')}"
        filtered.append(row)

    if inp.format == "csv":
        if not filtered:
            csv_output = ",".join(selected + ["citation"])
        else:
            headers = list(filtered[0].keys())
            lines = [",".join(headers)]
            for row in filtered:
                values = []
                for h in headers:
                    val = str(row.get(h, "")).replace('"', '""')
                    values.append(f'"{val}"')
                lines.append(",".join(values))
            csv_output = "\n".join(lines)
        return [types.TextContent(
            type="text",
            text=_success_response({"format": "csv", "content": csv_output}, source=meta_data.get("source", "live")),
        )]

    # Default: JSON
    return [types.TextContent(
        type="text",
        text=_success_response(
            {"format": "json", "count": len(filtered), "artifacts": filtered},
            source=meta_data.get("source", "live"),
        ),
    )]


# ── Mock data (fallback when CDLI API is unreachable) ────────────────────────
def _mock_search(query: str, page: int, page_size: int) -> dict[str, Any]:
    return {
        "results": [
            {
                "id": "P000001",
                "period": "Ur III (2112-2004 BCE)",
                "provenance": "Girsu (mod. Tello)",
                "transliteration_snippet": f"[result for '{query}'] 1. szu-nigin ...",
                "museum": "British Museum",
            },
            {
                "id": "P000002",
                "period": "Old Babylonian (2002-1595 BCE)",
                "provenance": "Nippur",
                "transliteration_snippet": f"[result for '{query}'] 1. a-na ...",
                "museum": "University of Pennsylvania",
            },
        ],
        "total_count": 2,
        "page": page,
        "page_size": page_size,
        "next_page_token": None,
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
    }


# ── Entry point ──────────────────────────────────────────────────────────────
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

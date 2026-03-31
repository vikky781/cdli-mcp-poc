# CDLI MCP Server — PoC

A minimal [Model Context Protocol](https://modelcontextprotocol.io/) server
exposing CDLI cuneiform artifact data as structured AI-callable tools.

Built as a proof-of-concept alongside [GSoC 2026 proposal](https://summerofcode.withgoogle.com/) submission for the
[Cuneiform Digital Library Initiative](https://cdli.mpiwg-berlin.mpg.de/).

## Architecture

```
┌─────────────────────────────────┐
│         MCP Client              │
│  (Claude Desktop, custom agent) │
└──────────┬──────────────────────┘
           │ stdio (MCP protocol)
┌──────────▼──────────────────────┐
│       Transport Layer           │
│      (stdio_server)             │
├─────────────────────────────────┤
│       Tool Registry             │
│  search_artifacts               │
│  get_artifact_metadata          │
│  export_artifacts               │
├─────────────────────────────────┤
│      Client Adapter             │
│  (httpx → CDLI REST API)        │
└─────────────────────────────────┘
```

## Tools

| Tool | Description |
|------|-------------|
| `search_artifacts` | Full-text search with period/location filters, pagination |
| `get_artifact_metadata` | Fetch complete artifact record(s) by CDLI ID — supports batch |
| `export_artifacts` | Export artifacts as JSON or CSV with selectable fields and citations |

## Setup

```bash
# Clone and install
git clone https://github.com/vikky781/cdli-mcp-poc.git
cd cdli-mcp-poc
pip install -r requirements.txt

# Configure (optional — defaults work for public endpoints)
cp .env.example .env
```

## Run

```bash
python cdli_mcp.py
```

The server speaks MCP over stdio — connect any MCP-compatible client
(Claude Desktop, custom agent, VS Code extension) and the tools are auto-discoverable.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `CDLI_BASE_URL` | `https://cdli.mpiwg-berlin.mpg.de/api/v1` | CDLI API base URL |
| `CDLI_API_KEY` | *(empty)* | API key for authenticated endpoints |
| `CDLI_TIMEOUT` | `15.0` | Request timeout in seconds |
| `CDLI_MAX_BATCH` | `20` | Max artifacts per batch request |

## Error Handling

All tools return structured error responses:

```json
{
  "error_code": "RATE_LIMITED",
  "message": "CDLI API rate limit reached",
  "suggested_action": "retry",
  "retry_after": 30
}
```

Error codes: `INVALID_INPUT`, `HTTP_ERROR`, `TIMEOUT`, `RATE_LIMITED`, `INTERNAL_ERROR`, `UNKNOWN_TOOL`

## Tests

```bash
pytest tests/ -v
```

## What's Next (Full GSoC Scope)

- Demo ReAct agent using Llama 3 via Ollama
- Async concurrent batch fetching with configurable limits
- Full pytest coverage with integration tests against CDLI staging
- Complete documentation with usage guide and example notebooks

## License

Built for [CDLI](https://cdli.mpiwg-berlin.mpg.de/) as part of GSoC 2026 proposal.

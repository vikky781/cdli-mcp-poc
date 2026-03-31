# CDLI MCP Server — PoC

A minimal [Model Context Protocol](https://modelcontextprotocol.io/) server 
exposing CDLI cuneiform artifact data as structured AI-callable tools.

Built as a proof-of-concept alongside GSoC 2026 proposal submission.

## Tools

| Tool | Description |
|------|-------------|
| `search_artifacts` | Full-text search with period filter, pagination |
| `get_artifact_metadata` | Fetch complete artifact record by CDLI ID |

## Run
```bash
pip install mcp pydantic httpx
python cdli_mcp.py
```

The server speaks MCP over stdio — connect any MCP-compatible client 
(Claude Desktop, custom agent) and the tools are auto-discoverable.

## What's next (full GSoC scope)
- Export tool (JSON/CSV with citation formatting)
- Batch metadata fetch with async concurrency
- Full error handling with `retry_after` for rate limits
- Demo ReAct agent using Llama 3 via Ollama
- pytest suite for all tools
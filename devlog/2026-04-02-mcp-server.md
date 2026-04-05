# MCP Server for Direct Health System Integration
**Date**: 2026-04-02  |  **Status**: Completed

## What Was Built
An MCP (Model Context Protocol) server that exposes DREAM-Chat as structured tools to OpenClaw. Instead of the agent reading AGENTS.md instructions and running shell `exec` commands, it now calls `health_ask()` as a first-class tool. No shell exec, no approval prompts, no JSON parsing.

## Architecture
```
WhatsApp → OpenClaw Gateway → Agent → health_ask() MCP tool → DreamChatClient → Flask API
```

The MCP server runs as a stdio process spawned by OpenClaw on demand. It wraps `DreamChatClient` and exposes two tools:
- `health_ask(question)` — routes through the full LLM + clinical guardrails pipeline
- `health_status()` — returns formatted metrics snapshot

## Key Files
| File | Purpose |
|------|---------|
| `dreamchat/mcp_server.py` | FastMCP server with health_ask and health_status tools |
| `scripts/dreamchat-mcp` | Entry point script (like scripts/dreamchat) |
| `openclaw/setup.sh` | Now registers MCP server via `openclaw mcp set` |
| `openclaw/agents-section.md` | Updated to reference MCP tool as primary, exec as fallback |

## Technical Decisions
- **MCP over shell exec**: MCP tools appear in the agent's tool list (structured, not text instructions). Tool calls don't need exec approval. Responses are structured text, not JSON that needs parsing.
- **FastMCP SDK**: Used Python's `mcp` package (v1.26.0) with FastMCP for minimal boilerplate. The server handles the MCP stdio protocol automatically.
- **Kept exec fallback**: AGENTS.md still includes the `exec dreamchat` fallback in case MCP isn't available (e.g., older OpenClaw versions).

## Usage
```bash
# Install (registers MCP server with OpenClaw):
bash openclaw/setup.sh

# Verify registration:
openclaw mcp list

# Restart gateway to pick up MCP config:
openclaw gateway stop && openclaw gateway start

# Run tests:
python -m pytest tests/test_dreamchat_cli.py -v
```

## Testing
103 tests pass (added 9 MCP-specific tests). Covers: tool imports, empty input, mock routing, server-down error, auth error, health_status formatting.

## Known Limitations
- The agent still decides WHEN to call the tool (LLM judgment for "is this a health question?"). But the HOW is now deterministic.
- MCP server requires the `mcp` Python package (installed by setup.sh).
- Gateway restart needed after first MCP registration.

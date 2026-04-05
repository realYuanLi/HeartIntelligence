# OpenClaw Routing Hardening
**Date**: 2026-04-02  |  **Status**: Completed

## What Was Built
Fixed three bugs in the OpenClaw-to-DREAM-Chat health routing pipeline that caused fresh installs to not route health questions, the CLI to produce tracebacks instead of JSON on auth failures, and the OpenClaw agent to return raw JSON metrics instead of formatted responses.

## Architecture
The routing chain: WhatsApp user -> OpenClaw gateway -> OpenClaw agent -> `dreamchat --json chat ask "question"` -> Flask `/api/message` -> LLM response -> agent extracts `data.response` -> sends verbatim to user.

## Key Files
| File | Purpose |
|------|---------|
| `dreamchat/client.py` | Added `DreamChatError` exception; `_login()` now raises it instead of `SystemExit` |
| `dreamchat/cli.py` | `main()` catches `DreamChatError` and exceptions, formats as JSON in `--json` mode |
| `openclaw/agents-section.md` | Canonical AGENTS.md section text (source of truth for routing instructions) |
| `openclaw/setup.sh` | Now injects/updates the DreamChat section in `~/.openclaw/workspace/AGENTS.md` |
| `openclaw/skills/dreamchat/SKILL.md` | Added bug #49873 notice; removed dangerous decision tree; all questions route through `chat ask` |
| `tests/test_dreamchat_cli.py` | Added 10 new tests for error-path JSON output and agents-section validation |

## Technical Decisions
- **`chat ask` is the only command for user questions**: The previous SKILL.md had a decision tree letting the agent choose between `health status`, `health trends`, and `chat ask`. This caused the agent to return raw JSON metrics. Now everything goes through `chat ask` which applies clinical guardrails.
- **AGENTS.md over SKILL.md**: Due to OpenClaw bug #49873, skill files aren't injected into the agent prompt. The canonical routing rules live in `agents-section.md` and get injected into AGENTS.md by `setup.sh`.
- **`DreamChatError` over `SystemExit`**: `SystemExit` bypasses the CLI's JSON formatting layer, producing tracebacks on stdout. A custom exception lets `main()` catch and format errors properly.

## Usage
```bash
# Fresh install on any OpenClaw machine:
cd DREAM-Chat && bash openclaw/setup.sh
dreamchat configure

# Run tests:
python -m pytest tests/test_dreamchat_cli.py -v
```

## Testing
94 tests pass. New tests cover: login failure JSON output, connection error JSON output, unexpected exception JSON output, no-credentials JSON output, agents-section content validation.

## Known Limitations
- OpenClaw skill injection bug (#49873) means AGENTS.md workaround is required until upstream fixes it.
- Exercise images from `chat ask` are silently dropped in the OpenClaw path (text-only channels).
- If user's message contains unescaped double quotes, shell parsing may break.

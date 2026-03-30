# DreamChat CLI + OpenClaw Integration
**Date**: 2026-03-30  |  **Status**: Completed

## What Was Built
A `dreamchat` CLI that wraps the DREAM-Chat Flask API as a stable, machine-readable control surface, plus an OpenClaw skill definition that teaches OpenClaw's agent how to use the CLI. This follows the Dr. Claw integration pattern: DREAM-Chat owns health reasoning, the CLI is the contract, and OpenClaw acts as a user-facing secretary across 20+ messaging channels. The existing standalone system (web UI + WhatsApp bridge) is unchanged -- OpenClaw integration is purely additive.

## Architecture
The CLI is a thin stdlib HTTP client (`urllib` + `http.cookiejar`) with zero new dependencies. It authenticates once via `POST /api/login`, caches session cookies at `~/.dreamchat/cookies.txt`, and auto-reauths on 401. Every `--json` command returns a stable `{"ok": true, "data": {...}}` / `{"ok": false, "error": "..."}` envelope that OpenClaw's agent parses. The OpenClaw skill file (`SKILL.md`) instructs the agent when to activate, which CLI command to use for each query type, and critically: never to add its own medical interpretation or store health data in OpenClaw's memory.

## Key Files
| File | Purpose |
|------|---------|
| `dreamchat/client.py` | HTTP client: auth, cookie caching, URL building, all API methods |
| `dreamchat/cli.py` | argparse dispatcher: 10 subcommands, JSON/human output, data formatting |
| `scripts/dreamchat` | Executable entry point with symlink-safe path resolution |
| `openclaw/skills/dreamchat/SKILL.md` | OpenClaw skill: routing rules, command reference, privacy guardrails |
| `openclaw/setup.sh` | One-line installer: symlinks CLI, copies skill, verifies connectivity |
| `tests/test_dreamchat_cli.py` | 84 tests: client, CLI, SKILL.md validation, all mocked (no server needed) |

## Technical Decisions
- **stdlib-only HTTP client**: Uses `urllib` + `MozillaCookieJar` instead of `requests` to avoid adding any dependency. The CLI must work in any Python 3.9+ environment.
- **`os.path.realpath` in entry point**: The `scripts/dreamchat` entry point uses `realpath` (not `abspath`) to correctly resolve the repo root when invoked via symlink from `~/.local/bin/`.
- **Centralized `_url()` method**: All URL construction uses a single `_url()` helper with `urljoin` to correctly handle sub-path deployments (e.g., `https://host/dreamchat/`).
- **No `health patient` command**: Deliberate omission. Raw patient data (diagnoses, medications, allergies) stays inside DREAM-Chat. Health questions go through `chat ask`, which returns curated LLM responses with clinical guardrails.

## Usage
```bash
# First-time setup
dreamchat configure
# Quick checks
dreamchat --json server status
dreamchat --json health status
dreamchat --json digest daily
# Health Q&A (uses full LLM + EHR context)
dreamchat --json chat ask "How does my medication interact with grapefruit?"
# OpenClaw integration
bash openclaw/setup.sh
```

## Testing
```bash
pytest tests/test_dreamchat_cli.py -v   # 84 tests, ~0.7s, no server needed
```
Coverage: client auth flow (login, reauth, 401 handling), all 10 CLI commands (success + error paths), session lifecycle, image encoding, JSON output contract, SKILL.md validation.

## Known Limitations
- Proactive messages (heartbeat) still deliver only via WhatsApp/web for standalone users. OpenClaw users can poll `digest daily` via OpenClaw's cron but don't get the 4-gate intelligent heartbeat triage. Planned for v2 as a file-based delivery method.
- `configure` command uses interactive `input()`, not suitable for non-interactive OpenClaw use. Env vars (`DREAMCHAT_URL`, `DREAMCHAT_EMAIL`, `DREAMCHAT_PASSWORD`) are the non-interactive alternative.
- Single persistent session per CLI user. No cross-channel session continuity between standalone WhatsApp and OpenClaw-routed messages.

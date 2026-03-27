# Multi-User WhatsApp Gateway
**Date**: 2026-03-27  |  **Status**: Completed

## What Was Built
A multi-user WhatsApp gateway that lets each authenticated user link their own WhatsApp account via QR code. The Node.js bridge manages per-user Baileys connections, forwards inbound messages to Flask for LLM processing, and delivers replies (including exercise images) back over WhatsApp. A settings UI provides connect/disconnect/QR-scan controls. Outbound cron messages are routed to the correct user's connection.

## Architecture
Two-process architecture managed by shell scripts:

1. **Node.js WhatsApp service** (TypeScript/Express, port 3001) -- runs Baileys WebSocket connections, exposes an internal REST API for connection management, and bridges messages to Flask.
2. **Flask backend** (Python/Gunicorn) -- owns session mapping (`sender_jid` to `session_id`), runs the LLM, and proxies connection-management requests from the UI to Node.js.

Message flow: `WhatsApp -> Baileys -> Node bridge -> Flask /api/whatsapp/message -> LLM -> reply -> Node bridge -> WhatsApp`. The `ConnectionManager` holds a `Map<userId, WhatsAppClient>` and auto-restores persisted sessions on startup by scanning `store/auth/{userId}/creds.json`.

## Key Files
| File | Purpose |
|------|---------|
| `whatsapp/src/connection-manager.ts` | Per-user connection lifecycle, session restore, max-connection cap |
| `whatsapp/src/api.ts` | Express REST API (connect, disconnect, status, health, QR generation) |
| `whatsapp/src/index.ts` | Entry point: message handling, outbound polling, graceful shutdown |
| `whatsapp/src/whatsapp.ts` | Baileys socket wrapper with proxy support |
| `whatsapp/src/bridge.ts` | Flask HTTP client with login/session cookie management |
| `whatsapp/flask_whatsapp.py` | Flask blueprint: session CRUD, message endpoint, Node.js proxy routes |
| `templates/settings_whatsapp.html` | WhatsApp settings page (QR display, status) |
| `static/settings_whatsapp.js` | Frontend: connect/disconnect actions, status polling |
| `scripts/dev.sh` | Dev startup with hot-reload for both processes |
| `scripts/start.sh` | Production startup with gevent worker |

## Technical Decisions
- **Flask as central controller**: Flask owns session state and LLM invocation; Node.js is a stateless message transport. This avoids duplicating auth and business logic.
- **Fire-and-forget connect**: `/connect` returns immediately; the UI polls `/status` every 2s until QR appears or connection completes.
- **Per-sender serialization**: Both Node (`inFlight` Set) and Flask (`_in_flight` Set) prevent concurrent processing for the same sender, avoiding interleaved replies.
- **API key auth**: `NODE_API_KEY` secures the internal Node API; skipped in dev mode with a logged warning.
- **Max 50 connections** via `MAX_CONNECTIONS` env var.

## Usage
```bash
# Development (hot-reload both processes)
./scripts/dev.sh

# Production
./scripts/start.sh

# Link WhatsApp: visit /settings/whatsapp, click Connect, scan QR
```

## Testing
63 tests passing. WhatsApp integration covered by existing test suite.

## Known Limitations
- Single gunicorn worker (`--workers 1`) required because Flask session state is in-memory.
- Auth files persist on disk (`store/auth/`); no automatic cleanup for deleted users.
- Outbound polling interval is fixed at 5 seconds (not configurable).
- QR code expires after ~60s (Baileys default); user must re-click Connect if missed.

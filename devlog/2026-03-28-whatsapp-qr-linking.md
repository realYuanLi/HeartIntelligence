# WhatsApp QR-Code Linking Flow

**Date**: 2026-03-28  |  **Status**: Completed

## What Was Built

Replaced manual password-based WhatsApp setup with a zero-config QR code linking flow. Users go to `/settings/whatsapp`, click **Connect WhatsApp**, scan a QR code on their phone, and they are linked. No `.env` editing or `BOT_PASSWORD` configuration required.

## Architecture

```
Browser (SSE)            Flask proxy             Node.js WhatsApp API
─────────────          ──────────────          ────────────────────
Click Connect  ──POST── /api/whatsapp/connect ──POST── /api/connections/:id/connect
EventSource    ──GET──  /api/whatsapp/qr-stream ──GET── /api/connections/:id/qr-stream
               ◄──SSE── qr events (data URL)   ◄──SSE── QR from Baileys
               ◄──SSE── status: connected       ◄──SSE── connection.update open
```

**Shared secret bootstrapping:** On Flask startup, `init_auth()` auto-generates a `BOT_PASSWORD` via `secrets.token_urlsafe(16)`, seeds the service account in SQLite, and writes the password to `whatsapp/store/.bot_secret` (mode 0600). The Node.js bridge reads it lazily via `getBotPassword()` with a cache that clears on 401 retry, surviving Flask restarts without manual coordination.

## Key Files

| File | Purpose |
|------|---------|
| `functions/auth.py` | Auto-generates bot password, writes `.bot_secret` |
| `whatsapp/src/config.ts` | Lazy `getBotPassword()` with `clearBotPasswordCache()` |
| `whatsapp/src/bridge.ts` | Clears password cache on login for stale-secret recovery |
| `whatsapp/src/whatsapp.ts` | QR/status event emitter (`onQrChange`, `onStatusChange`) |
| `whatsapp/src/api.ts` | SSE endpoint `/api/connections/:userId/qr-stream` |
| `whatsapp/flask_whatsapp.py` | SSE proxy, IDOR guards, path traversal validation |
| `static/settings_whatsapp.js` | EventSource SSE with polling fallback |
| `templates/settings_whatsapp.html` | Step-by-step scan instructions |
| `tests/test_whatsapp_qr.py` | 103 tests (1344 lines) |

## Security Fixes (from review)

- **Path traversal:** Session IDs validated against `^[a-f0-9]{12}$` regex before touching the filesystem.
- **IDOR protection:** Every endpoint checks `current_user.id == user_id` (or service account tier). Users cannot read or write another user's sessions.
- **Stale password cache:** `clearBotPasswordCache()` is called on every `FlaskBridge.login()`, so a Flask restart that rotates the bot password does not permanently lock out the bridge.

## Testing

```bash
python3 -m pytest tests/test_whatsapp_qr.py -v   # 103 tests pass
```

Covers: session ID validation (valid, traversal, injection), IDOR on all endpoints, bot secret file generation and permissions, service account seeding, SSE proxy wiring, and edge cases (empty inputs, malformed user IDs).

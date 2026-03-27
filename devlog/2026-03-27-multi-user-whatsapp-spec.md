# Implementation Spec: Multi-User WhatsApp Gateway + Production Server + Settings UI

## Goal

Transform DREAM-Chat's WhatsApp integration from a single hardcoded Baileys connection into a multi-user system where each registered user can link their own WhatsApp account through the web UI. Simultaneously, introduce a production-ready startup script that runs both the Flask (gunicorn) and Node.js (WhatsApp) services with hot-reload and graceful shutdown. Success means: any registered user can navigate to Settings > WhatsApp, scan a QR code, and begin receiving AI-powered WhatsApp replies on their own number -- with complete isolation between users.

## Technical Decisions

### 1. Single Node.js process with per-user connection Map
**Choice**: One Node.js process manages a `Map<userId, WhatsAppClient>` rather than spawning a child process per user.
**Reasoning**: The existing `WhatsAppClient` class is already self-contained. A Map gives O(1) lookup, shared memory for the outbound poll loop, and avoids the complexity of IPC. Baileys connections are lightweight WebSocket sessions -- a single process can comfortably manage dozens. If we ever need horizontal scaling, we can shard by user_id later.

### 2. Node.js exposes an Express REST API; Flask calls it (inversion of current flow)
**Choice**: Replace the current "Node.js calls Flask" architecture with "Flask calls Node.js" for connection management operations (connect, disconnect, status, QR). Keep the existing "Node.js calls Flask" flow for inbound message handling (this already works well).
**Reasoning**: The web UI lives in Flask. When a user clicks "Connect", Flask needs to tell Node.js to create a connection for that user_id. The cleanest boundary is an HTTP API on the Node.js side. Message handling continues in the current direction: Node.js receives a WhatsApp message, calls Flask's `/api/whatsapp/message` with the `user_id`, Flask runs the LLM, Node.js sends the reply.

### 3. Per-user auth state in `whatsapp/store/auth/{user_id}/`
**Choice**: Namespace auth credentials by `user_id` (the integer primary key from Flask's User model).
**Reasoning**: The current code stores everything in `whatsapp/store/auth/`. With multiple users, each needs an isolated Baileys `useMultiFileAuthState` directory. Using the numeric `user_id` (not email) avoids filesystem issues with special characters and is stable across email changes.

### 4. Express (not Fastify/Hono) for the Node.js REST API
**Choice**: Add `express` as a dependency.
**Reasoning**: Express is the standard, the team already knows it, and we only need ~6 endpoints. The overhead is negligible. Alternatives like Fastify add complexity for no benefit at this scale.

### 5. Polling for QR code updates (not SSE/WebSocket)
**Choice**: The web UI polls `GET /api/whatsapp/qr` every 2 seconds while the QR modal is open.
**Reasoning**: QR codes refresh every ~20 seconds in Baileys. Polling at 2s is simple, stateless, and avoids the complexity of managing SSE/WebSocket connections through gunicorn. The polling stops as soon as the connection opens (status changes to "connected"), so it is not wasteful.

### 6. gunicorn with --reload for development; plain gunicorn for production
**Choice**: A single `scripts/dev.sh` that starts gunicorn with `--reload` and the Node.js WhatsApp service with `tsx --watch`. A separate `scripts/start.sh` for production without file-watching.
**Reasoning**: `--reload` watches Python files and restarts workers automatically. `tsx --watch` does the same for TypeScript. Both are standard, zero-config solutions. The startup script manages both processes as children and forwards signals for graceful shutdown.

### 7. Flask proxies QR/status requests to Node.js (user never talks to Node.js directly)
**Choice**: The browser only communicates with Flask. Flask's `/api/whatsapp/*` endpoints proxy to the Node.js REST API, adding the `user_id` from the Flask session.
**Reasoning**: This maintains a single origin (no CORS), leverages Flask's existing auth (login_required), and keeps the Node.js service on a private port that is not exposed to the internet.

### 8. Bridge login uses per-user credentials (fix existing auth mismatch)
**Choice**: The Node.js bridge currently sends `{ username: FLASK_USERNAME, password: FLASK_PASSWORD }` but Flask's `api_login` expects `{ email, password }`. We fix this by having Node.js send `{ email, password }`. Additionally, for multi-user message handling, Node.js includes a `user_id` in the message payload so Flask routes to the correct user's chat history directory.
**Reasoning**: The current `.env` uses `FLASK_USERNAME=whatsapp_bot` which does not match any email in the User table. This is a latent bug. The fix is to use a dedicated service account email (e.g., `bot@dreamchat.local`) seeded on startup.

## File Plan

### Node.js (WhatsApp service) -- modify/create

| # | File | Action | Purpose |
|---|------|--------|---------|
| 1 | `whatsapp/package.json` | Modify | Add `express`, `@types/express`, `qrcode` (PNG generation) dependencies |
| 2 | `whatsapp/src/config.ts` | Modify | Add `NODE_API_PORT` (default 3001), remove single-user settings (`SELF_CHAT_ONLY`, `ALLOWLIST_JIDS`), add `BOT_EMAIL`/`BOT_PASSWORD` replacing `FLASK_USERNAME`/`FLASK_PASSWORD` |
| 3 | `whatsapp/src/connection-manager.ts` | Create | `ConnectionManager` class: `Map<number, WhatsAppClient>`, methods: `connect(userId)`, `disconnect(userId)`, `getStatus(userId)`, `getQr(userId)`, auto-restores persisted connections on startup |
| 4 | `whatsapp/src/whatsapp.ts` | Modify | Refactor `WhatsAppClient` constructor to accept `userId` and per-user `authDir`. Emit QR updates via a callback instead of printing to terminal. Remove global config references (`SELF_CHAT_ONLY`, `ALLOWLIST_JIDS`). Add `getQr()` getter, `getStatus()` method. |
| 5 | `whatsapp/src/api.ts` | Create | Express app with REST endpoints for connection management. Exports `startApiServer()`. |
| 6 | `whatsapp/src/bridge.ts` | Modify | Fix login payload: `{ email, password }` instead of `{ username, password }`. Add `user_id` to `sendWhatsAppMessage()`. |
| 7 | `whatsapp/src/index.ts` | Modify | Replace single-client startup with `ConnectionManager` initialization + `startApiServer()`. Restore persisted connections. |
| 8 | `whatsapp/src/db.ts` | Modify | Namespace database path by user_id or use a single DB with user_id column. |
| 9 | `whatsapp/.env` | Modify | Replace `FLASK_USERNAME`/`FLASK_PASSWORD` with `BOT_EMAIL`/`BOT_PASSWORD`. Remove single-user settings. |

### Flask (Python backend) -- modify/create

| # | File | Action | Purpose |
|---|------|--------|---------|
| 10 | `whatsapp/flask_whatsapp.py` | Modify | Add proxy endpoints for Node.js API: `/api/whatsapp/connect`, `/api/whatsapp/disconnect`, `/api/whatsapp/status`, `/api/whatsapp/qr`. Route inbound messages by `user_id`. Add `/settings/whatsapp` page route. |
| 11 | `functions/auth.py` | Modify | Seed a `bot@dreamchat.local` service account on startup (for Node.js bridge auth). Add backward-compat: accept `username` field as alias for `email` in `api_login`. |
| 12 | `app.py` | Modify | Add `whatsapp` to the settings subnav links rendering context. |

### Templates & Static -- create

| # | File | Action | Purpose |
|---|------|--------|---------|
| 13 | `templates/settings_whatsapp.html` | Create | Settings page with QR display, connection status, connect/disconnect buttons. Follows `settings_heartbeat.html` pattern. |
| 14 | `static/settings_whatsapp.js` | Create | JS for WhatsApp settings: poll QR, show status, handle connect/disconnect. Follows `settings_heartbeat.js` pattern. |

### Scripts -- create/modify

| # | File | Action | Purpose |
|---|------|--------|---------|
| 15 | `scripts/dev.sh` | Create | Development startup: gunicorn with `--reload` + Node.js with `tsx --watch`. Manages both processes, forwards SIGTERM/SIGINT. |
| 16 | `scripts/start.sh` | Create | Production startup: gunicorn (no reload) + `node dist/index.js`. |
| 17 | `start.sh` | Modify | Update to call `scripts/start.sh` (backward compat). |

## Implementation Steps

### Step 1: Fix auth mismatch and add service account
**Files**: `functions/auth.py`, `whatsapp/src/bridge.ts`, `whatsapp/src/config.ts`, `whatsapp/.env`
**What**:
1. In `functions/auth.py` `api_login()`, accept both `email` and `username` fields (check `data.get("email") or data.get("username")`).
2. In `init_auth()`, seed a `bot@dreamchat.local` service account alongside the demo user.
3. In `whatsapp/src/config.ts`, rename `FLASK_USERNAME` to `BOT_EMAIL` and `FLASK_PASSWORD` to `BOT_PASSWORD`.
4. In `whatsapp/src/bridge.ts`, change the login body from `{ username, password }` to `{ email: BOT_EMAIL, password: BOT_PASSWORD }`.
5. Update `whatsapp/.env` accordingly.

**Expected behavior**: Node.js bridge can authenticate to Flask using the new email-based auth. Existing functionality is unchanged.

### Step 2: Refactor WhatsAppClient for multi-user
**Files**: `whatsapp/src/whatsapp.ts`
**What**:
1. Add `userId: number` to the constructor.
2. Accept `authDir: string` in constructor instead of deriving from global `STORE_DIR`.
3. Replace QR terminal printing with a `qrCallback: (qr: string | null) => void` constructor option.
4. Add `private currentQr: string | null = null` and expose via `getQr(): string | null`.
5. Add `getStatus(): 'disconnected' | 'connecting' | 'connected' | 'qr'`.
6. Add `getPhoneNumber(): string | null` returning the linked phone number from `selfJid`.
7. Remove references to `SELF_CHAT_ONLY` and `ALLOWLIST_JIDS` (those become per-user config, out of scope for v1 -- all personal-number-mode users get self-chat-only by default).
8. Keep `ASSISTANT_HAS_OWN_NUMBER` and `ASSISTANT_NAME` as connection-level config passed via constructor options.

**Expected behavior**: `WhatsAppClient` is parameterized by userId and authDir. No global state. QR codes are captured in memory, not printed.

### Step 3: Create ConnectionManager
**Files**: `whatsapp/src/connection-manager.ts`
**What**:
1. `ConnectionManager` class with `private connections: Map<number, WhatsAppClient>`.
2. `async connect(userId: number): Promise<void>` -- creates a `WhatsAppClient` with auth dir `store/auth/{userId}/`, connects it, stores in map.
3. `async disconnect(userId: number): Promise<void>` -- calls `client.disconnect()`, removes from map.
4. `getStatus(userId: number): ConnectionStatus` -- returns status + phone number + QR if available.
5. `getClient(userId: number): WhatsAppClient | undefined` -- for message handling.
6. `async restoreAll(): Promise<void>` -- scans `store/auth/` for directories with `creds.json`, auto-connects each.
7. `listConnected(): number[]` -- returns all connected user IDs.

**Expected behavior**: Multiple WhatsApp connections can be created and managed independently. On startup, previously connected users are automatically reconnected.

### Step 4: Create Node.js REST API
**Files**: `whatsapp/src/api.ts`, `whatsapp/package.json`
**What**:
1. Add `express` and `@types/express` dependencies.
2. Add `qrcode` dependency (for generating QR as PNG data URI, since we can no longer use terminal rendering).
3. Create Express app with these endpoints:
   - `POST /api/connections/:userId/connect` -- start a connection
   - `POST /api/connections/:userId/disconnect` -- stop a connection
   - `GET /api/connections/:userId/status` -- returns `{ status, phoneNumber, qrDataUrl }`
   - `GET /api/connections` -- list all active connections
   - `GET /api/health` -- liveness check
4. Simple API key auth via `X-Api-Key` header (shared secret from env var `NODE_API_KEY`).
5. Export `startApiServer(manager: ConnectionManager): void`.

**Expected behavior**: Flask can manage WhatsApp connections by calling these endpoints. The API is internal-only (not exposed to the internet).

### Step 5: Rewire index.ts for multi-user
**Files**: `whatsapp/src/index.ts`, `whatsapp/src/db.ts`
**What**:
1. Replace single `WhatsAppClient` with `ConnectionManager`.
2. On startup: `initDatabase()`, `bridge.login()`, `manager.restoreAll()`, `startApiServer(manager)`.
3. The `handleMessage` callback now receives `userId` from the client and passes it to `bridge.sendWhatsAppMessage()`.
4. The outbound poll loop iterates over all connected users.
5. Update `db.ts` to include `user_id` column or namespace DB per user.

**Expected behavior**: The Node.js service starts, restores any previously-linked WhatsApp sessions, opens the REST API, and handles messages for all connected users.

### Step 6: Add Flask proxy endpoints
**Files**: `whatsapp/flask_whatsapp.py`
**What**:
1. Add config constant `NODE_WA_URL = os.environ.get("NODE_WA_URL", "http://localhost:3001")` and `NODE_API_KEY`.
2. Add endpoint: `POST /api/whatsapp/connect` -- calls Node.js `POST /api/connections/{user_id}/connect`. Requires `@login_required`.
3. Add endpoint: `POST /api/whatsapp/disconnect` -- calls Node.js `POST /api/connections/{user_id}/disconnect`.
4. Add endpoint: `GET /api/whatsapp/status` -- calls Node.js `GET /api/connections/{user_id}/status`. Returns status, phone number, QR data URL.
5. Add endpoint: `GET /settings/whatsapp` -- renders the settings page.
6. Update `/api/whatsapp/message` to accept `user_id` and route to the correct user's chat history.

**Expected behavior**: The web UI can manage WhatsApp connections through Flask. Flask proxies to Node.js with proper auth.

### Step 7: Build the Settings UI
**Files**: `templates/settings_whatsapp.html`, `static/settings_whatsapp.js`
**What**:
1. Create `settings_whatsapp.html` extending `base.html` with the settings subnav (add "WhatsApp" link).
2. Layout: a single card with connection status display and action button.
3. States:
   - **Disconnected**: Shows "Not connected" status + "Connect WhatsApp" button.
   - **QR Scanning**: Shows QR code image (auto-refreshed every 2s) + "Cancel" button + instruction text.
   - **Connected**: Shows green status badge + linked phone number + "Disconnect" button.
4. Create `settings_whatsapp.js`:
   - On load: `GET /api/whatsapp/status` to determine initial state.
   - Connect button: `POST /api/whatsapp/connect`, then start polling status every 2s.
   - Polling: `GET /api/whatsapp/status`, update QR image or show connected state.
   - Disconnect button: `POST /api/whatsapp/disconnect` with confirmation dialog.
   - Stop polling when connected or disconnected (not in QR state).

**Expected behavior**: User navigates to Settings > WhatsApp, clicks Connect, sees a QR code, scans with their phone, sees "Connected" with their phone number.

### Step 8: Update settings subnav across all settings pages
**Files**: All `templates/settings_*.html` files, relevant route handlers
**What**:
1. Add `<a href="/settings/whatsapp" ...>WhatsApp</a>` link to the settings subnav in every settings template.
2. Pass `settings_section="whatsapp"` from the new route handler.

**Expected behavior**: The "WhatsApp" tab appears in the settings subnav on all settings pages and is highlighted when active.

### Step 9: Create startup scripts
**Files**: `scripts/dev.sh`, `scripts/start.sh`, update root `start.sh`
**What**:
1. `scripts/dev.sh`:
   ```bash
   #!/bin/bash
   # Start Flask with hot-reload + Node.js WhatsApp service with watch mode
   trap 'kill 0' EXIT SIGINT SIGTERM

   cd whatsapp && npm run dev &
   WA_PID=$!

   gunicorn app:app \
     --bind 0.0.0.0:${PORT:-8000} \
     --workers 1 \
     --timeout 300 \
     --reload \
     --access-logfile - \
     --error-logfile - &
   FLASK_PID=$!

   wait
   ```
2. `scripts/start.sh`:
   ```bash
   #!/bin/bash
   # Production startup
   trap 'kill 0' EXIT SIGINT SIGTERM

   cd whatsapp && npm run build && npm run start &
   WA_PID=$!

   gunicorn app:app \
     --bind 0.0.0.0:${PORT:-8000} \
     --workers 1 \
     --worker-class gevent \
     --worker-connections 1000 \
     --timeout 300 \
     --access-logfile - \
     --error-logfile - &
   FLASK_PID=$!

   wait
   ```
3. Root `start.sh` calls `scripts/start.sh`.

**Expected behavior**: `./scripts/dev.sh` starts both services with file-watching. `./scripts/start.sh` starts both in production mode. Ctrl+C cleanly kills both.

### Step 10: Update environment configuration
**Files**: `whatsapp/.env`, `whatsapp/.env.example` (create)
**What**:
1. Create `.env.example` with all required variables documented.
2. Add `NODE_API_PORT=3001` and `NODE_API_KEY=<random>` to `.env`.
3. Add `NODE_WA_URL=http://localhost:3001` and `NODE_API_KEY=<same random>` to Flask's environment or a root `.env`.

**Expected behavior**: Both services can discover each other and authenticate internal API calls.

## API / Interface Contracts

### Node.js REST API (internal, port 3001)

All endpoints require header `X-Api-Key: <NODE_API_KEY>`.

#### `POST /api/connections/:userId/connect`
Start a WhatsApp connection for the given user.
- **Input**: URL param `userId` (integer)
- **Output (200)**: `{ success: true, status: "connecting" }`
- **Output (409)**: `{ success: false, message: "Already connected" }` (if connection is already open)
- **Output (401)**: `{ success: false, message: "Unauthorized" }` (bad API key)
- **Side effects**: Creates auth directory at `store/auth/{userId}/`, initiates Baileys connection. QR code becomes available within ~3 seconds.

#### `POST /api/connections/:userId/disconnect`
Disconnect and clean up a WhatsApp connection.
- **Input**: URL param `userId` (integer)
- **Output (200)**: `{ success: true }`
- **Output (404)**: `{ success: false, message: "No active connection" }`
- **Side effects**: Calls `client.disconnect()`, removes from ConnectionManager map. Auth files are preserved (so re-connect is instant if not logged out).

#### `GET /api/connections/:userId/status`
Get the current connection status and QR code (if scanning).
- **Input**: URL param `userId` (integer)
- **Output (200)**:
  ```json
  {
    "success": true,
    "status": "disconnected" | "connecting" | "qr" | "connected",
    "phoneNumber": "+8613812345678" | null,
    "qrDataUrl": "data:image/png;base64,..." | null
  }
  ```
  - `status: "disconnected"` -- no connection exists for this user
  - `status: "connecting"` -- connection initiated, waiting for QR generation
  - `status: "qr"` -- QR code is available, waiting for user to scan
  - `status: "connected"` -- WhatsApp is linked and active
  - `phoneNumber` is non-null only when `status === "connected"`
  - `qrDataUrl` is non-null only when `status === "qr"` (PNG data URI)
- **Output (401)**: Unauthorized

#### `GET /api/connections`
List all active connections.
- **Output (200)**:
  ```json
  {
    "success": true,
    "connections": [
      { "userId": 1, "status": "connected", "phoneNumber": "+8613812345678" },
      { "userId": 2, "status": "qr", "phoneNumber": null }
    ]
  }
  ```

#### `GET /api/health`
Liveness check.
- **Output (200)**: `{ "ok": true, "uptime": 12345, "connections": 2 }`

### Flask Proxy Endpoints (user-facing, port 8000)

All endpoints require `@login_required` (Flask-Login session cookie).

#### `POST /api/whatsapp/connect`
Initiate WhatsApp linking for the logged-in user.
- **Input**: None (user_id is derived from Flask session)
- **Output (200)**: `{ "success": true, "status": "connecting" }`
- **Output (409)**: `{ "success": false, "message": "Already connected" }`
- **Output (502)**: `{ "success": false, "message": "WhatsApp service unavailable" }` (Node.js is down)
- **Behavior**: Calls Node.js `POST /api/connections/{current_user.id}/connect`.

#### `POST /api/whatsapp/disconnect`
Disconnect the logged-in user's WhatsApp.
- **Input**: None
- **Output (200)**: `{ "success": true }`
- **Output (404)**: `{ "success": false, "message": "No active connection" }`
- **Behavior**: Calls Node.js `POST /api/connections/{current_user.id}/disconnect`.

#### `GET /api/whatsapp/status`
Get connection status for the logged-in user.
- **Output (200)**:
  ```json
  {
    "success": true,
    "status": "disconnected" | "connecting" | "qr" | "connected",
    "phone_number": "+8613812345678" | null,
    "qr_data_url": "data:image/png;base64,..." | null
  }
  ```
- **Output (502)**: `{ "success": false, "message": "WhatsApp service unavailable" }`
- **Behavior**: Calls Node.js `GET /api/connections/{current_user.id}/status`. If Node.js is unreachable, returns `status: "disconnected"` with a warning.

#### `GET /settings/whatsapp`
Render the WhatsApp settings page.
- **Output**: HTML page (settings_whatsapp.html)

#### `POST /api/whatsapp/message` (existing, modified)
Bridge sends inbound message. Now includes `user_id`.
- **Input**: `{ "sender_jid": "...", "sender_name": "...", "message": "...", "user_id": 1, "images": [...] }`
- **Output**: `{ "success": true, "assistant_message": "...", "session_id": "..." }`
- **Change**: The `user_id` field determines which user's chat history directory to use. If missing, falls back to the legacy `whatsapp_bot` directory.

## Acceptance Criteria

1. **Multi-user connection**: Two different users (user A and user B) can each link their own WhatsApp numbers simultaneously. Messages from user A's WhatsApp contacts do not appear in user B's chat history, and vice versa.

2. **QR code flow**: When a user clicks "Connect WhatsApp" on the settings page, a QR code appears within 5 seconds. After scanning with the WhatsApp mobile app, the page updates to show "Connected" with the linked phone number within 10 seconds.

3. **Reconnection persistence**: After restarting the Node.js service, all previously linked WhatsApp sessions are automatically restored without requiring users to re-scan QR codes.

4. **Disconnect flow**: Clicking "Disconnect" on the settings page disconnects the WhatsApp session. The status updates to "Disconnected" within 3 seconds. The user can re-connect by scanning a new QR code.

5. **Message routing**: An inbound WhatsApp message to user A's linked number results in an AI reply sent back through user A's WhatsApp connection, using user A's chat history for context.

6. **Outbound messages**: Cron job reminders and web-initiated messages are delivered through the correct user's WhatsApp connection (not a global one).

7. **Settings subnav**: "WhatsApp" appears as a tab in the settings subnav on all settings pages. Clicking it navigates to `/settings/whatsapp`.

8. **Hot-reload (dev)**: Modifying a `.py` file causes gunicorn to restart the worker. Modifying a `.ts` file causes the Node.js service to restart. No manual restart needed.

9. **Graceful shutdown**: `Ctrl+C` or `SIGTERM` cleanly shuts down both gunicorn and the Node.js process. No orphaned processes.

10. **Auth compatibility**: The Node.js bridge successfully authenticates to Flask using the seeded `bot@dreamchat.local` service account.

11. **Isolation**: Each user's Baileys auth state is stored in a separate directory (`whatsapp/store/auth/{user_id}/`). Deleting one user's auth directory does not affect others.

12. **Error resilience**: If the Node.js service is down, the WhatsApp settings page shows "Service unavailable" rather than crashing. If Flask is down, Node.js logs errors but does not crash.

## Edge Cases & Error Handling

### Connection lifecycle
- **User clicks Connect when already connected**: Return 409 with a clear message. UI shows current status.
- **User clicks Connect, then navigates away before scanning QR**: The connection attempt times out after 60 seconds (Baileys default). Next status poll returns "disconnected". No resource leak.
- **QR code expires before scanning**: Baileys generates a new QR automatically. The polling UI picks up the new QR seamlessly.
- **WhatsApp logs out the session remotely** (e.g., user unlinks from phone): Baileys fires `DisconnectReason.loggedOut`. ConnectionManager removes the connection and deletes the auth directory. Next status poll returns "disconnected".
- **Node.js process crashes**: All Baileys connections drop. On restart, `restoreAll()` reconnects users who have valid auth state.
- **Two browser tabs open on the same settings page**: Both poll status independently. One clicks Connect, the other sees the QR appear on next poll. No conflict.

### Network & infrastructure
- **Node.js service unreachable from Flask**: Flask proxy endpoints return 502 with `{ success: false, message: "WhatsApp service unavailable" }`. The UI shows a user-friendly error.
- **Flask service unreachable from Node.js**: Node.js logs errors when forwarding inbound messages. Messages are not lost -- the Node.js bridge already sends an error reply ("Sorry, I'm having trouble responding right now").
- **Proxy/firewall blocks WhatsApp WebSocket**: Per-user connections fail independently. Other users are unaffected. The failing connection shows "disconnected" status.

### Multi-user edge cases
- **Same WhatsApp number linked by two users**: Baileys will create separate sessions, but WhatsApp only allows one linked device of the same type. The second link will force-logout the first. This is a WhatsApp limitation, not something we can prevent. The first user's status will change to "disconnected".
- **User deletes their account while WhatsApp is connected**: The Flask layer should call disconnect on user deletion. If it does not, the orphaned connection runs until next restart, at which point `restoreAll()` skips user IDs that no longer exist in the database.
- **High number of concurrent connections**: Each Baileys connection uses ~10-30 MB of memory and one WebSocket. At 50+ users, memory monitoring becomes important. Add a configurable `MAX_CONNECTIONS` limit (default: 50).

### Database & storage
- **Auth directory corruption**: The existing creds backup/restore logic in `WhatsAppClient` handles this per-user. Corrupted creds for one user do not affect others.
- **Disk full**: Auth state writes will fail. Baileys handles this gracefully (connection continues with in-memory state). Log a warning.

## Out of Scope

1. **Per-user WhatsApp configuration** (allowlist, self-chat-only, assistant name prefix): All users get the same defaults (personal-number mode, self-chat only). Per-user config is a future enhancement.
2. **WhatsApp Business API**: This spec uses the unofficial Baileys library (personal WhatsApp). Migration to the official Business API is a separate project.
3. **Multiple WhatsApp numbers per user**: Each user gets exactly one WhatsApp connection.
4. **Group chat support**: Only 1-on-1 messages are handled (existing behavior).
5. **Message history migration**: Existing single-user chat history in `chat_history/whatsapp_bot/` is not automatically migrated to the new per-user structure.
6. **Rate limiting**: No per-user rate limiting on the Node.js API. Flask's existing auth is sufficient for now.
7. **Admin dashboard**: No admin UI to view/manage all users' WhatsApp connections. Only the `/api/connections` Node.js endpoint provides this (for operational use).
8. **End-to-end encryption of stored auth state**: Baileys auth files contain cryptographic keys stored in plaintext. Encrypting them at rest is a future security enhancement.
9. **Docker/containerization**: The startup scripts assume a bare-metal or VM deployment. Dockerfiles are a separate task.
10. **Horizontal scaling**: The design assumes a single server. Sharding connections across multiple Node.js instances would require a coordination layer (Redis, etc.).

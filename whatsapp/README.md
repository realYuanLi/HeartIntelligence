# DREAM-Chat WhatsApp Bridge

Connects the DREAM-Chat bot to WhatsApp using your **existing personal number** as the bot's identity. The bridge runs as a Linked Device (like WhatsApp Web), so your phone session is unaffected.

## How it works

```
WhatsApp user → Baileys (WA Web protocol) → bridge → Flask /api/message → Chatbot → reply → WhatsApp user
```

Each WhatsApp sender gets their own Flask chat session, so conversation history is preserved per-user.

## Personal-number mode

This bridge is designed for **personal-number mode**: the linked account is your real WhatsApp number, not a dedicated bot number. Key safeguards:

- **Allowlist** — only phone numbers you list in `ALLOWLIST_JIDS` receive bot replies. This prevents the bot from responding to every contact on your personal account.
- **Self-chat** — your own number is always allowed so you can test the bot by messaging yourself.
- **Reply prefix** — bot replies are prefixed with `DREAM:` (configurable via `ASSISTANT_NAME`) so you can distinguish them from your own messages in the same thread.
- **fromMe filtering** — messages sent from the bridge itself are never re-processed. Messages sent from your phone (self-chat) are correctly forwarded to the bot.

## Requirements

- Node.js 20+
- The DREAM-Chat Flask server running (default: `http://localhost:8000`)
- Your existing WhatsApp number (no second phone needed)

## Setup

### 1. Configure the bridge

```bash
cd whatsapp
cp .env.example .env
# Required: set FLASK_PASSWORD to match WHATSAPP_BOT_PASSWORD in root .env
# Recommended: set ALLOWLIST_JIDS to the phone numbers that should reach the bot
# Optional: set WA_PROXY_URL if behind a proxy (e.g. mainland China)
```

### 2. Install dependencies

```bash
cd whatsapp
npm install
```

### 3. Authenticate with WhatsApp (one-time)

**Option A — Pairing code (recommended, no camera needed):**

```bash
npm run auth:pairing -- +8613812345678
# Replace with your actual WhatsApp number (include country code)
```

WhatsApp will give you an 8-digit code. Enter it in:
**WhatsApp → Settings → Linked Devices → Link a Device → Link with phone number instead**

**Option B — QR code:**

```bash
npm run auth
```

Scan the QR code with WhatsApp: **Settings → Linked Devices → Link a Device**

After either method, credentials are saved to `store/auth/` and never need to be re-entered unless you log out.

### 4. Start the bridge

```bash
# Make sure the Flask server is running first:
cd .. && python app.py

# Then start the bridge:
cd whatsapp && npm run dev
```

### 5. Test it

Message yourself on WhatsApp (self-chat). You should see a reply prefixed with `DREAM:`.

To allow other people to reach the bot, add their numbers to `ALLOWLIST_JIDS` in `whatsapp/.env`.

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `FLASK_BASE_URL` | `http://localhost:8000` | URL of the Flask server |
| `FLASK_USERNAME` | `whatsapp_bot` | Flask account username |
| `FLASK_PASSWORD` | _(required)_ | Flask account password |
| `ASSISTANT_NAME` | `DREAM` | Prefix on bot replies |
| `ASSISTANT_HAS_OWN_NUMBER` | `false` | Set `true` only for a dedicated bot number |
| `ALLOWLIST_JIDS` | _(empty — allow all)_ | Comma-separated phone numbers allowed to reach the bot |
| `WA_PROXY_URL` | _(none)_ | SOCKS5/HTTP proxy for WhatsApp traffic |
| `LOG_LEVEL` | `info` | Pino log level |

## File structure

```
whatsapp/
├── src/
│   ├── config.ts      # Environment-based configuration
│   ├── logger.ts      # Pino logger instance
│   ├── whatsapp.ts    # Baileys connection: auth, receive, send, LID translation
│   ├── bridge.ts      # HTTP client for Flask API
│   ├── db.ts          # SQLite: maps WA senders to Flask sessions
│   └── index.ts       # Main orchestrator
├── store/             # Runtime data (auth credentials, SQLite DB) — gitignored
├── .env.example
├── package.json
└── tsconfig.json
```

## Persistent state

| Path | Contents |
|------|----------|
| `store/auth/` | WhatsApp session credentials (Baileys multi-file auth) |
| `store/whatsapp.db` | SQLite DB mapping WhatsApp JIDs to Flask session IDs |

To reset WhatsApp authentication, delete `store/auth/` and restart.  
To reset all conversation history, delete `store/whatsapp.db`.

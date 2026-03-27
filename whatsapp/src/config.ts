import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '..', '.env') });

// Directory where auth credentials and the SQLite DB are stored
export const STORE_DIR = path.join(__dirname, '..', 'store');

// URL of the running DREAM-Chat Flask server
export const FLASK_BASE_URL = process.env.FLASK_BASE_URL ?? 'http://localhost:8000';

// Credentials used to authenticate with the Flask API (service account)
export const BOT_EMAIL = process.env.BOT_EMAIL ?? 'bot@dreamchat.local';
export const BOT_PASSWORD = (() => {
  const pw = process.env.BOT_PASSWORD;
  if (!pw) {
    throw new Error(
      'BOT_PASSWORD environment variable is required. '
      + 'Set it in whatsapp/.env to match the Flask-side BOT_PASSWORD.',
    );
  }
  return pw;
})();

// Port for the internal Node.js REST API
export const NODE_API_PORT = parseInt(process.env.NODE_API_PORT ?? '3001', 10);

// Shared secret for Node.js API authentication
export const NODE_API_KEY = process.env.NODE_API_KEY ?? '';

// How often (ms) the message poll loop runs
export const POLL_INTERVAL_MS = 500;

// Log level: 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'fatal'
export const LOG_LEVEL = process.env.LOG_LEVEL ?? 'info';

// Optional SOCKS5/HTTP proxy for routing WhatsApp WebSocket traffic
// e.g. socks5://127.0.0.1:7897 or http://127.0.0.1:7890
// Auto-detected from system proxy if not set explicitly
export const WA_PROXY_URL: string | null = (() => {
  if (process.env.WA_PROXY_URL) return process.env.WA_PROXY_URL;
  if (process.env.ALL_PROXY) return process.env.ALL_PROXY;
  if (process.env.all_proxy) return process.env.all_proxy;
  return null;
})();

// Propagate proxy to HTTPS_PROXY so axios (used by Baileys internally) picks it up
if (WA_PROXY_URL && !process.env.HTTPS_PROXY) {
  process.env.HTTPS_PROXY = WA_PROXY_URL;
  process.env.HTTP_PROXY = WA_PROXY_URL;
}

// ── Personal-number mode defaults ─────────────────────────────────────────────
//
// In multi-user mode every user connects their personal WhatsApp number.
// ASSISTANT_HAS_OWN_NUMBER and ASSISTANT_NAME are kept as connection-level
// defaults and can be passed into WhatsAppClient via constructor options.
export const ASSISTANT_HAS_OWN_NUMBER: boolean =
  process.env.ASSISTANT_HAS_OWN_NUMBER === 'true';

// Display name prepended to bot replies in personal-number mode.
export const ASSISTANT_NAME: string = process.env.ASSISTANT_NAME ?? '[Health Pal]';

import fs from 'fs';
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

// Path to the shared secret file written by Flask on startup.
const BOT_SECRET_PATH = path.join(STORE_DIR, '.bot_secret');

/**
 * Lazily read the bot password.  Checked in order:
 * 1. BOT_PASSWORD environment variable
 * 2. store/.bot_secret file (written by Flask)
 * Throws a clear error only when actually called and neither source exists.
 */
let _cachedBotPassword: string | null = null;

export function getBotPassword(): string {
  if (_cachedBotPassword) return _cachedBotPassword;

  const envPw = process.env.BOT_PASSWORD;
  if (envPw) {
    _cachedBotPassword = envPw;
    return envPw;
  }

  try {
    const filePw = fs.readFileSync(BOT_SECRET_PATH, 'utf-8').trim();
    if (filePw) {
      _cachedBotPassword = filePw;
      return filePw;
    }
  } catch {
    // File does not exist yet — fall through to error
  }

  throw new Error(
    'BOT_PASSWORD not found. Set the BOT_PASSWORD environment variable '
    + `or ensure Flask has written ${BOT_SECRET_PATH}.`,
  );
}

/**
 * Clear the cached bot password so the next call to getBotPassword()
 * re-reads from the env var or .bot_secret file.  Called by FlaskBridge
 * when a 401 indicates the cached password is stale (e.g. after Flask restart).
 */
export function clearBotPasswordCache(): void {
  _cachedBotPassword = null;
}

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

import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '..', '.env') });

// Directory where auth credentials and the SQLite DB are stored
export const STORE_DIR = path.join(__dirname, '..', 'store');

// URL of the running DREAM-Chat Flask server
export const FLASK_BASE_URL = process.env.FLASK_BASE_URL ?? 'http://localhost:8000';

// Credentials used to authenticate with the Flask API
export const FLASK_USERNAME = process.env.FLASK_USERNAME ?? 'whatsapp_bot';
export const FLASK_PASSWORD = process.env.FLASK_PASSWORD ?? '';

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

// ── Personal-number mode ──────────────────────────────────────────────────────
//
// Set ASSISTANT_HAS_OWN_NUMBER=true only when the linked WhatsApp account is a
// dedicated bot number that no human uses for personal messaging.
//
// When false (default — personal number mode):
//   • Bot replies are prefixed with ASSISTANT_NAME so you can tell them apart
//     from your own messages in the same chat thread.
//   • Only JIDs listed in ALLOWLIST_JIDS receive bot replies, preventing the
//     bot from responding to every contact on your personal account.
//   • Self-chat (messages from your own number to itself) is allowed so you
//     can test the bot by messaging yourself.
export const ASSISTANT_HAS_OWN_NUMBER: boolean =
  process.env.ASSISTANT_HAS_OWN_NUMBER === 'true';

// Display name prepended to bot replies in personal-number mode.
export const ASSISTANT_NAME: string = process.env.ASSISTANT_NAME ?? '[Health Pal]';

// When true, the bot ONLY responds to self-chat (messages you send to your
// own number). All other conversations are silently ignored.
export const SELF_CHAT_ONLY: boolean =
  (process.env.SELF_CHAT_ONLY ?? 'true') === 'true';

// Comma-separated list of WhatsApp JIDs (or bare phone numbers) that the bot
// will respond to. Ignored when SELF_CHAT_ONLY is true.
// Leave empty to allow all senders (not recommended on a personal number).
// Example: "+8613812345678,+12025551234"
//
// Self-chat (your own number) is always implicitly allowed so you can test
// the bot without adding yourself to this list.
export const ALLOWLIST_JIDS: Set<string> = (() => {
  const raw = process.env.ALLOWLIST_JIDS ?? '';
  if (!raw.trim()) return new Set<string>();
  return new Set(
    raw.split(',').map((s) => {
      const cleaned = s.trim().replace(/\D/g, '');
      return cleaned ? `${cleaned}@s.whatsapp.net` : '';
    }).filter(Boolean),
  );
})();

/**
 * Standalone WhatsApp authentication script.
 *
 * Run once to link the server to your WhatsApp account.
 * Credentials are saved to store/auth/ and reused on every subsequent start.
 *
 * Two modes:
 *   QR code:      npx tsx src/auth.ts
 *   Pairing code: npx tsx src/auth.ts --pairing-code +8613812345678
 *
 * Pairing code is recommended — no camera needed, works headlessly.
 * After pairing, anyone who messages your WhatsApp number reaches the bot.
 */
import fs from 'fs';
import path from 'path';

import makeWASocket, {
  DisconnectReason,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';
import qrcode from 'qrcode-terminal';
import { SocksProxyAgent } from 'socks-proxy-agent';
import { HttpsProxyAgent } from 'https-proxy-agent';

import { STORE_DIR, WA_PROXY_URL } from './config.js';
import { baileysLogger, logger } from './logger.js';

// Re-use the same fetchWaVersion helper from whatsapp.ts logic inline here
import https from 'https';
import type { WAVersion } from '@whiskeysockets/baileys';

const BAILEYS_FALLBACK_VERSION: WAVersion = [2, 3000, 1023223821];

function buildAgent(): SocksProxyAgent | HttpsProxyAgent<string> | undefined {
  if (!WA_PROXY_URL) return undefined;
  return WA_PROXY_URL.startsWith('socks')
    ? new SocksProxyAgent(WA_PROXY_URL)
    : new HttpsProxyAgent(WA_PROXY_URL);
}

async function fetchWaVersion(
  agent: SocksProxyAgent | HttpsProxyAgent<string> | undefined,
): Promise<WAVersion> {
  return new Promise((resolve) => {
    const req = https.request(
      {
        hostname: 'web.whatsapp.com',
        path: '/sw.js',
        method: 'GET',
        headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36' },
        ...(agent ? { agent } : {}),
      },
      (res) => {
        let body = '';
        res.on('data', (c: Buffer) => { body += c.toString(); });
        res.on('end', () => {
          const match = body.match(/\\?"client_revision\\?":\s*(\d+)/);
          resolve(match?.[1] ? [2, 3000, +match[1]] : BAILEYS_FALLBACK_VERSION);
        });
      },
    );
    req.on('error', () => resolve(BAILEYS_FALLBACK_VERSION));
    req.end();
  });
}

// ── CLI argument parsing ──────────────────────────────────────────────────────

const args = process.argv.slice(2);
const usePairingCode = args.includes('--pairing-code');
const phoneArg = (() => {
  const idx = args.findIndex((a) => a === '--pairing-code');
  // Accept phone as next positional arg after the flag
  const next = args[idx + 1];
  return next && !next.startsWith('--') ? next : undefined;
})();

// ── Auth flow ─────────────────────────────────────────────────────────────────

const AUTH_DIR = path.join(STORE_DIR, 'auth');

async function connect(phoneNumber?: string, isReconnect = false): Promise<void> {
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

  if (state.creds.registered && !isReconnect) {
    console.log('\n✓ Already authenticated with WhatsApp.');
    console.log('  Delete store/auth/ and re-run to re-authenticate.\n');
    process.exit(0);
  }

  const agent = buildAgent();
  const version = await fetchWaVersion(agent);
  console.log(`  WA version: ${version.join('.')}`);

  const sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, baileysLogger),
    },
    printQRInTerminal: false,
    logger: baileysLogger,
    browser: ['DREAM-Chat', 'Desktop', '1.0.0'],
    ...(agent ? { agent, fetchAgent: agent } : {}),
  });

  // Request pairing code after socket initialises (pairing code mode only)
  if (usePairingCode && phoneNumber && !state.creds.me) {
    setTimeout(async () => {
      try {
        // Strip spaces and leading +
        const cleaned = phoneNumber.replace(/\D/g, '');
        const code = await sock.requestPairingCode(cleaned);
        console.log('\n┌─────────────────────────────────────┐');
        console.log(`│  Pairing code: ${code.padEnd(21)}│`);
        console.log('└─────────────────────────────────────┘\n');
        console.log('  1. Open WhatsApp on your phone');
        console.log('  2. Settings → Linked Devices → Link a Device');
        console.log('  3. Tap "Link with phone number instead"');
        console.log(`  4. Enter the code above\n`);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        console.error(`\n✗ Failed to request pairing code: ${msg}`);
        process.exit(1);
      }
    }, 3000);
  }

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('\n  Scan this QR code with WhatsApp:\n');
      console.log('  1. Open WhatsApp on your phone');
      console.log('  2. Settings → Linked Devices → Link a Device');
      console.log('  3. Point your camera at the QR code below\n');
      qrcode.generate(qr, { small: true });
    }

    if (connection === 'close') {
      const reason = (lastDisconnect?.error as { output?: { statusCode?: number } })
        ?.output?.statusCode;

      if (reason === DisconnectReason.loggedOut) {
        console.log('\n✗ Logged out. Delete store/auth/ and try again.');
        process.exit(1);
      } else if (reason === DisconnectReason.timedOut) {
        console.log('\n✗ Timed out. Please try again.');
        process.exit(1);
      } else if (reason === 515) {
        // Stream error after pairing succeeds — reconnect to finish handshake
        console.log('\n⟳ Reconnecting to complete pairing...');
        connect(phoneNumber, true);
      } else {
        console.log(`\n✗ Connection closed (reason: ${reason}). Please try again.`);
        process.exit(1);
      }
    }

    if (connection === 'open') {
      console.log('\n✓ Successfully authenticated with WhatsApp!');
      console.log('  Credentials saved to store/auth/');
      console.log('  You can now run: npm run dev\n');
      setTimeout(() => process.exit(0), 1000);
    }
  });
}

async function main(): Promise<void> {
  console.log('\nDREAM-Chat WhatsApp Authentication\n');

  if (usePairingCode) {
    let phone = phoneArg;
    if (!phone) {
      // Prompt interactively if not passed as argument
      const readline = await import('readline');
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      phone = await new Promise<string>((resolve) => {
        rl.question('  Enter your WhatsApp phone number (with country code, e.g. +8613812345678): ', (ans) => {
          rl.close();
          resolve(ans.trim());
        });
      });
    }
    console.log(`  Mode: pairing code  |  Phone: ${phone}`);
    await connect(phone);
  } else {
    console.log('  Mode: QR code');
    console.log('  Tip: use --pairing-code +<number> to avoid scanning\n');
    await connect();
  }
}

main().catch((err) => {
  console.error('Authentication failed:', err);
  process.exit(1);
});

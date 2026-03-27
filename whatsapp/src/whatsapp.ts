import fsSync from 'fs';
import path from 'path';

import makeWASocket, {
  DisconnectReason,
  downloadMediaMessage,
  proto,
  WASocket,
  WAVersion,
  makeCacheableSignalKeyStore,
  normalizeMessageContent,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';
import { SocksProxyAgent } from 'socks-proxy-agent';
import { HttpsProxyAgent } from 'https-proxy-agent';
import https from 'https';

import { WA_PROXY_URL } from './config.js';
import { baileysLogger, logger } from './logger.js';

// Fallback version used when the live fetch fails
const BAILEYS_FALLBACK_VERSION: WAVersion = [2, 3000, 1023223821];

function buildAgent(): SocksProxyAgent | HttpsProxyAgent<string> | undefined {
  if (!WA_PROXY_URL) return undefined;
  if (WA_PROXY_URL.startsWith('socks')) {
    logger.info({ proxy: WA_PROXY_URL }, 'Using SOCKS proxy for WhatsApp');
    return new SocksProxyAgent(WA_PROXY_URL);
  }
  logger.info({ proxy: WA_PROXY_URL }, 'Using HTTP proxy for WhatsApp');
  return new HttpsProxyAgent(WA_PROXY_URL);
}

/**
 * Fetch the latest WA Web version directly, routing through the proxy agent.
 * Bypasses Baileys' built-in fetchLatestWaWebVersion which uses axios with
 * responseType:'json' and doesn't accept a custom agent correctly.
 */
async function fetchWaVersion(
  agent: SocksProxyAgent | HttpsProxyAgent<string> | undefined,
): Promise<WAVersion> {
  return new Promise((resolve) => {
    const options: https.RequestOptions = {
      hostname: 'web.whatsapp.com',
      path: '/sw.js',
      method: 'GET',
      headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36' },
      ...(agent ? { agent } : {}),
    };
    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', (chunk: Buffer) => { body += chunk.toString(); });
      res.on('end', () => {
        const match = body.match(/\\?"client_revision\\?":\s*(\d+)/);
        if (match?.[1]) {
          const version: WAVersion = [2, 3000, +match[1]];
          logger.info({ version, isLatest: true }, 'WA Web version');
          resolve(version);
        } else {
          logger.warn('Could not parse WA version from sw.js, using fallback');
          resolve(BAILEYS_FALLBACK_VERSION);
        }
      });
    });
    req.on('error', (err) => {
      logger.warn({ err }, 'Failed to fetch WA version, using fallback');
      resolve(BAILEYS_FALLBACK_VERSION);
    });
    req.end();
  });
}

export interface InboundMessage {
  id: string;
  senderJid: string;
  senderName: string;
  content: string;
  timestamp: string;
  /** Base64 data URIs of attached images. */
  images?: string[];
}

export type ConnectionStatus = 'disconnected' | 'connecting' | 'qr' | 'connected';

export type OnMessageCallback = (msg: InboundMessage) => void;
export type QrCallback = (qr: string | null) => void;

export interface WhatsAppClientOptions {
  userId: number;
  authDir: string;
  onMessage: OnMessageCallback;
  assistantHasOwnNumber?: boolean;
  assistantName?: string;
}

/**
 * Manages the WhatsApp connection via Baileys.
 * Emits inbound text messages through the provided callback.
 * Handles reconnection automatically.
 */
const RECONNECT_DELAYS_MS = [2000, 5000, 10000, 30000, 60000];

/**
 * Sequentialised creds-save with best-effort backup (mirrors OpenClaw's
 * safeSaveCreds pattern).  Prevents concurrent writes from corrupting
 * creds.json and keeps a single backup copy so we can recover after
 * abrupt restarts.
 */
const credsSaveQueues = new Map<number, Promise<void>>();

function enqueueSaveCreds(
  userId: number,
  authDir: string,
  saveCreds: () => Promise<void>,
): void {
  const prev = credsSaveQueues.get(userId) ?? Promise.resolve();
  const next = prev
    .then(async () => {
      const credsPath = path.join(authDir, 'creds.json');
      const backupPath = path.join(authDir, 'creds.backup.json');
      try {
        const raw = fsSync.existsSync(credsPath) ? fsSync.readFileSync(credsPath, 'utf-8') : null;
        if (raw) {
          JSON.parse(raw);
          fsSync.copyFileSync(credsPath, backupPath);
        }
      } catch { /* keep existing backup */ }
      await saveCreds();
    })
    .catch((err) => {
      logger.warn({ err, userId }, 'WhatsApp creds save error');
    });
  credsSaveQueues.set(userId, next);
}

const MESSAGE_STORE_MAX = 500;

export class WhatsAppClient {
  readonly userId: number;
  private readonly authDir: string;
  private readonly onMessage: OnMessageCallback;
  private readonly assistantHasOwnNumber: boolean;
  private readonly assistantName: string;

  private sock!: WASocket;
  private status: ConnectionStatus = 'disconnected';
  private currentQr: string | null = null;
  private outgoingQueue: Array<{ jid: string; text: string }> = [];
  private flushing = false;
  private reconnectAttempt = 0;
  private loggedOut = false;

  // Phone JID of the linked account (e.g. "8613812345678@s.whatsapp.net").
  private selfJid: string | null = null;

  // LID -> phone JID cache for WhatsApp's newer LID addressing.
  private lidToPhoneMap: Record<string, string> = {};

  // Stores sent message content keyed by message ID for retransmission.
  private sentMsgStore = new Map<string, proto.IMessage>();

  constructor(options: WhatsAppClientOptions) {
    this.userId = options.userId;
    this.authDir = options.authDir;
    this.onMessage = options.onMessage;
    this.assistantHasOwnNumber = options.assistantHasOwnNumber ?? false;
    this.assistantName = options.assistantName ?? '[Health Pal]';
  }

  async connect(): Promise<void> {
    this.loggedOut = false;
    this.status = 'connecting';
    return new Promise<void>((resolve, reject) => {
      this.connectInternal(resolve).catch(reject);
    });
  }

  private async connectInternal(onFirstOpen?: () => void): Promise<void> {
    fsSync.mkdirSync(this.authDir, { recursive: true });

    // Restore creds from backup if main creds.json is missing or corrupted
    const credsPath = path.join(this.authDir, 'creds.json');
    const backupPath = path.join(this.authDir, 'creds.backup.json');
    if (!fsSync.existsSync(credsPath) && fsSync.existsSync(backupPath)) {
      logger.info({ userId: this.userId }, 'Restoring creds.json from backup');
      fsSync.copyFileSync(backupPath, credsPath);
    }

    const { state, saveCreds } = await useMultiFileAuthState(this.authDir);

    const proxyAgent = buildAgent();
    const version = await fetchWaVersion(proxyAgent);

    this.sock = makeWASocket({
      version,
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, baileysLogger),
      },
      printQRInTerminal: false,
      logger: baileysLogger,
      browser: ['DREAM-Chat', 'Desktop', '1.0.0'],
      syncFullHistory: false,
      markOnlineOnConnect: false,
      getMessage: async (key: proto.IMessageKey) => {
        if (key.id) return this.sentMsgStore.get(key.id);
        return undefined;
      },
      ...(proxyAgent ? { agent: proxyAgent, fetchAgent: proxyAgent } : {}),
    });

    this.sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        this.currentQr = qr;
        this.status = 'qr';
        logger.info({ userId: this.userId }, 'QR code available');
      }

      if (connection === 'close') {
        this.status = 'disconnected';
        this.currentQr = null;
        const reason = (
          lastDisconnect?.error as { output?: { statusCode?: number } }
        )?.output?.statusCode;
        const shouldReconnect = reason !== DisconnectReason.loggedOut;

        logger.info({ userId: this.userId, reason, shouldReconnect }, 'Connection closed');

        if (shouldReconnect && !this.loggedOut) {
          const delay = RECONNECT_DELAYS_MS[
            Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)
          ];
          this.reconnectAttempt++;
          this.status = 'connecting';
          logger.info({ userId: this.userId, attempt: this.reconnectAttempt, delayMs: delay }, 'Reconnecting...');
          setTimeout(() => {
            this.connectInternal().catch((err) =>
              logger.error({ userId: this.userId, err }, 'Reconnect attempt failed'),
            );
          }, delay);
        } else {
          this.loggedOut = true;
          logger.info({ userId: this.userId }, 'Logged out — delete auth directory to re-authenticate');
          // Clean up auth directory on logout
          try {
            fsSync.rmSync(this.authDir, { recursive: true, force: true });
          } catch { /* best effort */ }
        }
      } else if (connection === 'open') {
        this.status = 'connected';
        this.currentQr = null;
        this.reconnectAttempt = 0;
        logger.info({ userId: this.userId }, 'Connected to WhatsApp');

        // Capture own JID and build LID -> phone mapping for self-chat detection
        if (this.sock.user) {
          const phoneUser = this.sock.user.id.split(':')[0];
          this.selfJid = `${phoneUser}@s.whatsapp.net`;
          if (this.sock.user.lid) {
            const lidUser = this.sock.user.lid.split(':')[0];
            this.lidToPhoneMap[lidUser] = this.selfJid;
          }
          logger.info({ userId: this.userId, selfJid: this.selfJid }, 'Own JID recorded');
        }

        this.sock.sendPresenceUpdate('available').catch((err) =>
          logger.warn({ userId: this.userId, err }, 'Failed to send presence update'),
        );

        this.flushOutgoingQueue().catch((err) =>
          logger.error({ userId: this.userId, err }, 'Failed to flush outgoing queue'),
        );

        if (onFirstOpen) {
          onFirstOpen();
          onFirstOpen = undefined;
        }
      }
    });

    this.sock.ev.on('creds.update', () => enqueueSaveCreds(this.userId, this.authDir, saveCreds));

    this.sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return;

      for (const msg of messages) {
        if (!msg.message) continue;

        const normalized = normalizeMessageContent(msg.message);
        if (!normalized) continue;

        const rawJid = msg.key.remoteJid;
        if (!rawJid || rawJid === 'status@broadcast') continue;

        // Only handle direct (1-on-1) messages, not group chats
        if (rawJid.endsWith('@g.us')) continue;

        // Translate LID-based JIDs to phone JIDs
        const altJid = (msg.key as { remoteJidAlt?: string }).remoteJidAlt;
        const chatJid = altJid && !altJid.endsWith('@lid')
          ? altJid
          : await this.translateJid(rawJid);

        const fromMe = msg.key.fromMe ?? false;

        if (this.assistantHasOwnNumber) {
          // Dedicated bot number: skip all outgoing messages
          if (fromMe) continue;
        } else {
          // Personal number mode: skip messages sent from this linked device
          // but allow self-chat messages sent from the phone
          const isSelfChat = this.selfJid !== null && chatJid === this.selfJid;
          if (fromMe && !isSelfChat) continue;
        }

        const content =
          normalized.conversation ||
          normalized.extendedTextMessage?.text ||
          normalized.imageMessage?.caption ||
          '';

        // Download image if present
        const images: string[] = [];
        if (normalized.imageMessage) {
          try {
            const buffer = await downloadMediaMessage(msg, 'buffer', {});
            const mimetype = normalized.imageMessage.mimetype || 'image/jpeg';
            images.push(`data:${mimetype};base64,${(buffer as Buffer).toString('base64')}`);
          } catch (err) {
            logger.warn({ err, msgId: msg.key.id, userId: this.userId }, 'Failed to download image');
          }
        }

        if (!content.trim() && images.length === 0) continue;

        // In personal-number mode, bot replies are prefixed with ASSISTANT_NAME.
        // When WhatsApp echoes the sent message back, drop it to break the loop.
        if (!this.assistantHasOwnNumber && content.startsWith(`${this.assistantName}:`)) continue;

        // In personal-number mode with self-chat only (default for v1)
        const isSelf = this.selfJid !== null && chatJid === this.selfJid;
        if (!isSelf) {
          logger.debug({ userId: this.userId, chatJid }, 'Self-chat-only mode, ignoring');
          continue;
        }

        const timestamp = new Date(
          Number(msg.messageTimestamp) * 1000,
        ).toISOString();

        const senderName = msg.pushName || chatJid.split('@')[0];

        this.onMessage({
          id: msg.key.id ?? `${chatJid}-${Date.now()}`,
          senderJid: chatJid,
          senderName,
          content,
          timestamp,
          ...(images.length > 0 ? { images } : {}),
        });
      }
    });
  }

  async sendMessage(jid: string, text: string): Promise<void> {
    if (this.status !== 'connected') {
      this.outgoingQueue.push({ jid, text });
      logger.info({ userId: this.userId, jid, queueSize: this.outgoingQueue.length }, 'WA disconnected, message queued');
      return;
    }

    try {
      const result = await this.sock.sendMessage(jid, { text });
      logger.info(
        { userId: this.userId, jid, length: text.length, msgId: result?.key?.id, status: result?.status },
        'Message sent',
      );
      if (result?.key?.id && result.message) {
        this.storeSentMessage(result.key.id, result.message);
      }
    } catch (err) {
      this.outgoingQueue.push({ jid, text });
      logger.warn({ userId: this.userId, jid, err, queueSize: this.outgoingQueue.length }, 'Send failed, message queued');
    }
  }

  async sendImage(jid: string, imageBuffer: Buffer, caption?: string): Promise<void> {
    if (this.status !== 'connected') {
      logger.warn({ userId: this.userId, jid }, 'WA disconnected, cannot send image');
      return;
    }

    try {
      const payload: { image: Buffer; caption?: string } = { image: imageBuffer };
      if (caption) payload.caption = caption;
      const result = await this.sock.sendMessage(jid, payload);
      logger.info(
        { userId: this.userId, jid, msgId: result?.key?.id, caption: caption ?? '' },
        'Image sent',
      );
      if (result?.key?.id && result.message) {
        this.storeSentMessage(result.key.id, result.message);
      }
    } catch (err) {
      logger.warn({ userId: this.userId, jid, err }, 'Failed to send image');
    }
  }

  isConnected(): boolean {
    return this.status === 'connected';
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  getQr(): string | null {
    return this.currentQr;
  }

  getPhoneNumber(): string | null {
    if (this.status !== 'connected' || !this.selfJid) return null;
    const phone = this.selfJid.split('@')[0];
    return `+${phone}`;
  }

  async disconnect(): Promise<void> {
    this.loggedOut = true;
    this.status = 'disconnected';
    this.currentQr = null;
    this.sock?.end(undefined);
  }

  async setTyping(jid: string, isTyping: boolean): Promise<void> {
    try {
      await this.sock.sendPresenceUpdate(isTyping ? 'composing' : 'paused', jid);
    } catch (err) {
      logger.debug({ userId: this.userId, jid, err }, 'Failed to update typing status');
    }
  }

  /**
   * Translate a LID-based JID (ending in @lid) to its phone-based equivalent.
   */
  private async translateJid(jid: string): Promise<string> {
    if (!jid.endsWith('@lid')) return jid;
    const lidUser = jid.split('@')[0].split(':')[0];

    const cached = this.lidToPhoneMap[lidUser];
    if (cached) return cached;

    try {
      const pn = await this.sock.signalRepository.lidMapping.getPNForLID(jid);
      if (pn) {
        const phoneJid = `${pn.split('@')[0].split(':')[0]}@s.whatsapp.net`;
        this.lidToPhoneMap[lidUser] = phoneJid;
        logger.debug({ lidJid: jid, phoneJid }, 'Translated LID to phone JID');
        return phoneJid;
      }
    } catch (err) {
      logger.debug({ err, jid }, 'Failed to resolve LID via signalRepository');
    }

    return jid;
  }

  private async flushOutgoingQueue(): Promise<void> {
    if (this.flushing || this.outgoingQueue.length === 0) return;
    this.flushing = true;
    try {
      logger.info({ userId: this.userId, count: this.outgoingQueue.length }, 'Flushing outgoing queue');
      while (this.outgoingQueue.length > 0) {
        const item = this.outgoingQueue.shift()!;
        const result = await this.sock.sendMessage(item.jid, { text: item.text });
        if (result?.key?.id && result.message) {
          this.storeSentMessage(result.key.id, result.message);
        }
        logger.info({ userId: this.userId, jid: item.jid }, 'Queued message sent');
      }
    } finally {
      this.flushing = false;
    }
  }

  private storeSentMessage(id: string, message: proto.IMessage): void {
    this.sentMsgStore.set(id, message);
    if (this.sentMsgStore.size > MESSAGE_STORE_MAX) {
      const oldest = this.sentMsgStore.keys().next().value;
      if (oldest) this.sentMsgStore.delete(oldest);
    }
  }
}

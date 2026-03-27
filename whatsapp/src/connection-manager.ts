import fsSync from 'fs';
import path from 'path';

import { STORE_DIR } from './config.js';
import { logger } from './logger.js';
import { ConnectionStatus, OnMessageCallback, WhatsAppClient } from './whatsapp.js';

export interface ConnectionInfo {
  userId: number;
  status: ConnectionStatus;
  phoneNumber: string | null;
  qr: string | null;
}

const MAX_CONNECTIONS = parseInt(process.env.MAX_CONNECTIONS ?? '50', 10);

/**
 * Manages multiple WhatsApp connections, one per user.
 * Provides connect/disconnect/status operations and auto-restores
 * persisted sessions on startup.
 */
export class ConnectionManager {
  private connections = new Map<number, WhatsAppClient>();
  private readonly onMessage: (userId: number, msg: Parameters<OnMessageCallback>[0]) => void;

  constructor(
    onMessage: (userId: number, msg: Parameters<OnMessageCallback>[0]) => void,
  ) {
    this.onMessage = onMessage;
  }

  /**
   * Start a WhatsApp connection for the given user.
   * Creates auth directory at store/auth/{userId}/.
   */
  async connect(userId: number): Promise<void> {
    const existing = this.connections.get(userId);
    if (existing && existing.getStatus() !== 'disconnected') {
      throw new Error('Already connected');
    }

    if (this.connections.size >= MAX_CONNECTIONS) {
      throw new Error(`Maximum connections (${MAX_CONNECTIONS}) reached`);
    }

    const authDir = this.authDirForUser(userId);
    const client = new WhatsAppClient({
      userId,
      authDir,
      onMessage: (msg) => this.onMessage(userId, msg),
    });

    this.connections.set(userId, client);

    // connect() resolves when the first 'open' event fires or rejects on error.
    // If it throws, we clean up the map entry.
    try {
      await client.connect();
    } catch (err) {
      this.connections.delete(userId);
      throw err;
    }
  }

  /**
   * Disconnect a user's WhatsApp session and remove from the active map.
   * Auth files are preserved so re-connect can be instant.
   */
  async disconnect(userId: number): Promise<void> {
    const client = this.connections.get(userId);
    if (!client) {
      throw new Error('No active connection');
    }
    await client.disconnect();
    this.connections.delete(userId);
  }

  /**
   * Get the current connection status for a user.
   */
  getStatus(userId: number): ConnectionInfo {
    const client = this.connections.get(userId);
    if (!client) {
      return {
        userId,
        status: 'disconnected',
        phoneNumber: null,
        qr: null,
      };
    }
    return {
      userId,
      status: client.getStatus(),
      phoneNumber: client.getPhoneNumber(),
      qr: client.getQr(),
    };
  }

  /**
   * Get the WhatsAppClient instance for a user, if it exists.
   */
  getClient(userId: number): WhatsAppClient | undefined {
    return this.connections.get(userId);
  }

  /**
   * Scan store/auth/ for directories containing creds.json and
   * auto-reconnect each user. Called once on startup.
   */
  async restoreAll(): Promise<void> {
    const authRoot = path.join(STORE_DIR, 'auth');
    if (!fsSync.existsSync(authRoot)) return;

    const entries = fsSync.readdirSync(authRoot, { withFileTypes: true });
    const restorePromises: Promise<void>[] = [];

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const userId = parseInt(entry.name, 10);
      if (isNaN(userId)) continue;

      const credsPath = path.join(authRoot, entry.name, 'creds.json');
      if (!fsSync.existsSync(credsPath)) continue;

      logger.info({ userId }, 'Restoring WhatsApp session');
      restorePromises.push(
        this.connect(userId).catch((err) => {
          logger.error({ userId, err }, 'Failed to restore WhatsApp session');
        }),
      );
    }

    await Promise.allSettled(restorePromises);
    logger.info({ restoredCount: restorePromises.length }, 'Session restore complete');
  }

  /**
   * Return all user IDs with active (non-disconnected) connections.
   */
  listConnected(): number[] {
    const result: number[] = [];
    for (const [userId, client] of this.connections) {
      if (client.getStatus() !== 'disconnected') {
        result.push(userId);
      }
    }
    return result;
  }

  /**
   * Return status info for all active connections.
   */
  listAll(): ConnectionInfo[] {
    const result: ConnectionInfo[] = [];
    for (const [userId, client] of this.connections) {
      result.push({
        userId,
        status: client.getStatus(),
        phoneNumber: client.getPhoneNumber(),
        qr: null, // Don't expose QR codes in list view
      });
    }
    return result;
  }

  private authDirForUser(userId: number): string {
    return path.join(STORE_DIR, 'auth', String(userId));
  }
}

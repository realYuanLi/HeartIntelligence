import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';

import { STORE_DIR } from './config.js';

let db: Database.Database;

function createSchema(database: Database.Database): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      sender_jid   TEXT PRIMARY KEY,
      flask_session_id TEXT NOT NULL,
      created_at   TEXT NOT NULL,
      updated_at   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      sender_jid   TEXT NOT NULL,
      role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
      content      TEXT NOT NULL,
      timestamp    TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_messages_jid ON messages(sender_jid, timestamp);
  `);
}

export function initDatabase(): void {
  const dbPath = path.join(STORE_DIR, 'whatsapp.db');
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  db = new Database(dbPath);
  createSchema(db);
}

/**
 * Return the Flask session_id associated with this WhatsApp sender,
 * or null if no conversation exists yet.
 */
export function getFlaskSessionId(senderJid: string): string | null {
  const row = db
    .prepare('SELECT flask_session_id FROM conversations WHERE sender_jid = ?')
    .get(senderJid) as { flask_session_id: string } | undefined;
  return row?.flask_session_id ?? null;
}

/**
 * Store (or update) the Flask session_id for a WhatsApp sender.
 */
export function setFlaskSessionId(senderJid: string, flaskSessionId: string): void {
  const now = new Date().toISOString();
  db.prepare(`
    INSERT INTO conversations (sender_jid, flask_session_id, created_at, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(sender_jid) DO UPDATE SET
      flask_session_id = excluded.flask_session_id,
      updated_at = excluded.updated_at
  `).run(senderJid, flaskSessionId, now, now);
}

/**
 * Append a message to the local log (for audit / debugging purposes).
 */
export function logMessage(
  senderJid: string,
  role: 'user' | 'assistant',
  content: string,
): void {
  db.prepare(`
    INSERT INTO messages (sender_jid, role, content, timestamp)
    VALUES (?, ?, ?, ?)
  `).run(senderJid, role, content, new Date().toISOString());
}

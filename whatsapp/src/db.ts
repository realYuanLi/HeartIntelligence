import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';

import { STORE_DIR } from './config.js';

let db: Database.Database;

function createSchema(database: Database.Database): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      sender_jid   TEXT NOT NULL,
      user_id      INTEGER NOT NULL DEFAULT 0,
      flask_session_id TEXT NOT NULL,
      created_at   TEXT NOT NULL,
      updated_at   TEXT NOT NULL,
      PRIMARY KEY (sender_jid, user_id)
    );

    CREATE TABLE IF NOT EXISTS messages (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      sender_jid   TEXT NOT NULL,
      user_id      INTEGER NOT NULL DEFAULT 0,
      role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
      content      TEXT NOT NULL,
      timestamp    TEXT NOT NULL
    );
  `);
}

/**
 * Create indexes that depend on columns added by migrations.
 * Called after migrateSchema to avoid referencing columns that don't exist yet.
 */
function createIndexes(database: Database.Database): void {
  database.exec(`
    CREATE INDEX IF NOT EXISTS idx_messages_jid_user ON messages(sender_jid, user_id, timestamp);
  `);
}

/**
 * Run migrations to add user_id column if the database predates multi-user.
 */
function migrateSchema(database: Database.Database): void {
  const tableInfo = database.pragma('table_info(conversations)') as Array<{ name: string }>;
  const hasUserId = tableInfo.some((col) => col.name === 'user_id');
  if (!hasUserId) {
    database.exec(`
      ALTER TABLE conversations ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0;
    `);
    // Recreate primary key by creating new table (SQLite limitation)
    database.exec(`
      CREATE TABLE IF NOT EXISTS conversations_new (
        sender_jid   TEXT NOT NULL,
        user_id      INTEGER NOT NULL DEFAULT 0,
        flask_session_id TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        PRIMARY KEY (sender_jid, user_id)
      );
      INSERT OR IGNORE INTO conversations_new SELECT sender_jid, user_id, flask_session_id, created_at, updated_at FROM conversations;
      DROP TABLE conversations;
      ALTER TABLE conversations_new RENAME TO conversations;
    `);
  }

  const msgInfo = database.pragma('table_info(messages)') as Array<{ name: string }>;
  const msgHasUserId = msgInfo.some((col) => col.name === 'user_id');
  if (!msgHasUserId) {
    database.exec(`
      ALTER TABLE messages ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0;
      CREATE INDEX IF NOT EXISTS idx_messages_jid_user ON messages(sender_jid, user_id, timestamp);
    `);
  }
}

export function initDatabase(): void {
  const dbPath = path.join(STORE_DIR, 'whatsapp.db');
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  db = new Database(dbPath);
  createSchema(db);
  migrateSchema(db);
  createIndexes(db);
}

/**
 * Return the Flask session_id associated with this WhatsApp sender,
 * or null if no conversation exists yet.
 */
export function getFlaskSessionId(senderJid: string, userId = 0): string | null {
  const row = db
    .prepare('SELECT flask_session_id FROM conversations WHERE sender_jid = ? AND user_id = ?')
    .get(senderJid, userId) as { flask_session_id: string } | undefined;
  return row?.flask_session_id ?? null;
}

/**
 * Store (or update) the Flask session_id for a WhatsApp sender.
 */
export function setFlaskSessionId(senderJid: string, flaskSessionId: string, userId = 0): void {
  const now = new Date().toISOString();
  db.prepare(`
    INSERT INTO conversations (sender_jid, user_id, flask_session_id, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(sender_jid, user_id) DO UPDATE SET
      flask_session_id = excluded.flask_session_id,
      updated_at = excluded.updated_at
  `).run(senderJid, userId, flaskSessionId, now, now);
}

/**
 * Append a message to the local log (for audit / debugging purposes).
 */
export function logMessage(
  senderJid: string,
  role: 'user' | 'assistant',
  content: string,
  userId = 0,
): void {
  db.prepare(`
    INSERT INTO messages (sender_jid, user_id, role, content, timestamp)
    VALUES (?, ?, ?, ?, ?)
  `).run(senderJid, userId, role, content, new Date().toISOString());
}

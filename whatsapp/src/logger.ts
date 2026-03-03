import pino from 'pino';
import { LOG_LEVEL } from './config.js';

export const logger = pino({
  level: LOG_LEVEL,
  transport:
    process.env.NODE_ENV !== 'production'
      ? { target: 'pino-pretty', options: { colorize: true } }
      : undefined,
});

// Baileys receives a child logger that only surfaces warnings and above.
// This suppresses its verbose internal Signal protocol session dumps
// (e.g. "Closing session: SessionEntry { ... }") while keeping our own
// INFO-level bridge logs visible.
export const baileysLogger = logger.child({}, { level: 'warn' });

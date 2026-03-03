/**
 * Monkey-patch global console methods to suppress verbose (and sensitive)
 * output from the `libsignal` library.
 *
 * libsignal's session_record.js and session_cipher.js call console.info /
 * console.warn / console.error directly, bypassing our pino logger.  The
 * messages dump entire SessionEntry objects — including private cryptographic
 * keys — to stdout.  We intercept those calls and drop them silently.
 *
 * IMPORTANT: This module must be imported BEFORE any module that transitively
 * loads libsignal (i.e. before Baileys / whatsapp.ts).
 */

const SUPPRESSED_PREFIXES = [
  'Closing session',
  'Opening session',
  'Session already closed',
  'Session already open',
  'Closing open session',
  'Closing stale open session',
  'Removing old closed session',
  'Migrating session to',
  'Decrypted message with closed session',
  'Failed to decrypt message with any known session',
  'Session error:',
  'V1 session storage migration error',
  'Unhandled bucket type',
];

function shouldSuppress(args: unknown[]): boolean {
  if (args.length === 0) return false;
  const first = args[0];
  if (typeof first !== 'string') return false;
  return SUPPRESSED_PREFIXES.some((prefix) => first.startsWith(prefix));
}

const originalInfo = console.info.bind(console);
const originalWarn = console.warn.bind(console);
const originalError = console.error.bind(console);

console.info = (...args: unknown[]) => {
  if (!shouldSuppress(args)) originalInfo(...args);
};

console.warn = (...args: unknown[]) => {
  if (!shouldSuppress(args)) originalWarn(...args);
};

console.error = (...args: unknown[]) => {
  if (!shouldSuppress(args)) originalError(...args);
};

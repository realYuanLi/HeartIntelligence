import './suppress-signal-logs.js';

import { FlaskBridge } from './bridge.js';
import { ASSISTANT_HAS_OWN_NUMBER, ASSISTANT_NAME } from './config.js';
import { initDatabase, logMessage } from './db.js';
import { logger } from './logger.js';
import { InboundMessage, WhatsAppClient } from './whatsapp.js';

// Prevent concurrent processing for the same sender
const inFlight = new Set<string>();

const bridge = new FlaskBridge();

/**
 * Handle a single inbound WhatsApp message:
 * 1. Forward the message to Flask (which owns session management).
 * 2. Send the reply back over WhatsApp.
 */
async function handleMessage(
  msg: InboundMessage,
  wa: WhatsAppClient,
): Promise<void> {
  const { senderJid, senderName, content } = msg;

  // Serialize per-sender to avoid interleaved replies
  if (inFlight.has(senderJid)) {
    logger.debug({ senderJid }, 'Message already in-flight, dropping duplicate');
    return;
  }
  inFlight.add(senderJid);

  try {
    logger.info({ senderJid, senderName, content }, 'Received message');
    logMessage(senderJid, 'user', content);

    await wa.setTyping(senderJid, true);

    // Flask manages the sender_jid → session_id mapping and runs the LLM
    const reply = await bridge.sendWhatsAppMessage(senderJid, senderName, content);

    // In personal-number mode, prefix replies so they're distinguishable from
    // your own messages in the same chat thread.
    const outgoing = ASSISTANT_HAS_OWN_NUMBER ? reply : `${ASSISTANT_NAME}: ${reply}`;

    logMessage(senderJid, 'assistant', reply);
    await wa.setTyping(senderJid, false);
    await wa.sendMessage(senderJid, outgoing);

    logger.info({ senderJid, replyLength: reply.length }, 'Reply sent');
  } catch (err) {
    logger.error({ senderJid, err }, 'Failed to handle message');
    await wa.setTyping(senderJid, false);
    await wa.sendMessage(
      senderJid,
      "Sorry, I'm having trouble responding right now. Please try again in a moment.",
    );
  } finally {
    inFlight.delete(senderJid);
  }
}

/**
 * Poll Flask for outbound messages (from cron jobs) and deliver them.
 * Runs every 5 seconds while the WhatsApp client is connected.
 */
async function pollOutboundMessages(wa: WhatsAppClient): Promise<void> {
  try {
    const messages = await bridge.pollOutbound();
    for (const msg of messages) {
      try {
        const prefix = ASSISTANT_HAS_OWN_NUMBER ? '' : `${ASSISTANT_NAME}: `;
        await wa.sendMessage(msg.target_jid, `${prefix}${msg.message}`);
        await bridge.ackOutbound(msg.msg_id);
        logger.info(
          { targetJid: msg.target_jid, msgId: msg.msg_id },
          'Outbound cron message delivered',
        );
      } catch (err) {
        logger.error(
          { targetJid: msg.target_jid, msgId: msg.msg_id, err },
          'Failed to deliver outbound message',
        );
      }
    }
  } catch (err) {
    logger.debug({ err }, 'Outbound poll error (will retry)');
  }
}

async function main(): Promise<void> {
  initDatabase();
  logger.info('Database initialized');

  // Verify Flask is reachable before connecting to WhatsApp
  try {
    await bridge.login();
  } catch (err) {
    logger.fatal({ err }, 'Cannot connect to Flask server — is it running?');
    process.exit(1);
  }

  const wa = new WhatsAppClient((msg: InboundMessage) => {
    // Fire-and-forget; errors are caught inside handleMessage
    handleMessage(msg, wa).catch((err) =>
      logger.error({ err }, 'Unhandled error in handleMessage'),
    );
  });

  // Graceful shutdown
  let outboundTimer: ReturnType<typeof setInterval> | null = null;
  const shutdown = async (signal: string) => {
    logger.info({ signal }, 'Shutting down');
    if (outboundTimer) clearInterval(outboundTimer);
    await wa.disconnect();
    process.exit(0);
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));

  logger.info('Connecting to WhatsApp...');
  await wa.connect();
  logger.info('DREAM-Chat WhatsApp bridge is running');

  // Start polling for outbound cron job messages every 5 seconds
  outboundTimer = setInterval(() => {
    if (wa.isConnected()) {
      pollOutboundMessages(wa).catch((err) =>
        logger.error({ err }, 'Unhandled outbound poll error'),
      );
    }
  }, 5000);
  logger.info('Outbound message polling started (5s interval)');
}

main().catch((err) => {
  logger.fatal({ err }, 'Fatal startup error');
  process.exit(1);
});

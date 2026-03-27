import './suppress-signal-logs.js';

import { startApiServer } from './api.js';
import { FlaskBridge } from './bridge.js';
import { ASSISTANT_HAS_OWN_NUMBER, ASSISTANT_NAME } from './config.js';
import { ConnectionManager } from './connection-manager.js';
import { initDatabase, logMessage } from './db.js';
import { logger } from './logger.js';
import { InboundMessage } from './whatsapp.js';

// Prevent concurrent processing for the same sender per user
const inFlight = new Set<string>();

const bridge = new FlaskBridge();

/**
 * Handle a single inbound WhatsApp message:
 * 1. Forward the message to Flask (which owns session management).
 * 2. Send the reply back over WhatsApp.
 */
async function handleMessage(
  userId: number,
  msg: InboundMessage,
  manager: ConnectionManager,
): Promise<void> {
  const { senderJid, senderName, content, images } = msg;
  const flightKey = `${userId}:${senderJid}`;

  // Serialize per-sender to avoid interleaved replies
  if (inFlight.has(flightKey)) {
    logger.debug({ userId, senderJid }, 'Message already in-flight, dropping duplicate');
    return;
  }
  inFlight.add(flightKey);

  const wa = manager.getClient(userId);
  if (!wa) {
    logger.warn({ userId, senderJid }, 'No WhatsApp client for user, dropping message');
    inFlight.delete(flightKey);
    return;
  }

  try {
    logger.info({ userId, senderJid, senderName, content, hasImages: !!(images && images.length) }, 'Received message');
    logMessage(senderJid, 'user', content, userId);

    await wa.setTyping(senderJid, true);

    // Flask manages the sender_jid -> session_id mapping and runs the LLM
    const { reply, exerciseImages } = await bridge.sendWhatsAppMessage(senderJid, senderName, content, images, userId);

    // In personal-number mode, prefix replies so they're distinguishable from
    // your own messages in the same chat thread.
    const outgoing = ASSISTANT_HAS_OWN_NUMBER ? reply : `${ASSISTANT_NAME}: ${reply}`;

    logMessage(senderJid, 'assistant', reply, userId);
    await wa.setTyping(senderJid, false);
    await wa.sendMessage(senderJid, outgoing);

    // Send exercise images as separate image messages (cap at 5)
    const imagesToSend = exerciseImages.slice(0, 5);
    for (const img of imagesToSend) {
      try {
        const imageBuffer = await bridge.fetchExerciseImage(img.url);
        await wa.sendImage(senderJid, imageBuffer, img.name);
      } catch (imgErr) {
        logger.warn({ userId, senderJid, imageUrl: img.url, err: imgErr }, 'Failed to send exercise image');
      }
    }

    logger.info({ userId, senderJid, replyLength: reply.length, exerciseImageCount: imagesToSend.length }, 'Reply sent');
  } catch (err) {
    logger.error({ userId, senderJid, err }, 'Failed to handle message');
    await wa.setTyping(senderJid, false);
    await wa.sendMessage(
      senderJid,
      "Sorry, I'm having trouble responding right now. Please try again in a moment.",
    );
  } finally {
    inFlight.delete(flightKey);
  }
}

/**
 * Poll Flask for outbound messages (from cron jobs) and deliver them
 * through the appropriate user's WhatsApp connection.
 *
 * Each outbound message may include a `user_id` field that routes the message
 * to the correct user's WhatsApp connection. When `user_id` is absent (legacy
 * messages), all connected users are tried as a fallback.
 */
async function pollOutboundMessages(manager: ConnectionManager): Promise<void> {
  try {
    const messages = await bridge.pollOutbound();
    for (const msg of messages) {
      let delivered = false;

      // If the outbound message specifies a user_id, route directly
      if (msg.user_id != null) {
        const client = manager.getClient(msg.user_id);
        if (client && client.isConnected()) {
          try {
            const prefix = msg.skip_prefix || ASSISTANT_HAS_OWN_NUMBER ? '' : `${ASSISTANT_NAME}: `;
            await client.sendMessage(msg.target_jid, `${prefix}${msg.message}`);
            await bridge.ackOutbound(msg.msg_id);
            logger.info(
              { userId: msg.user_id, targetJid: msg.target_jid, msgId: msg.msg_id },
              'Outbound cron message delivered',
            );
            delivered = true;
          } catch (err) {
            logger.error(
              { userId: msg.user_id, targetJid: msg.target_jid, msgId: msg.msg_id, err },
              'Failed to deliver outbound message to target user',
            );
          }
        } else {
          logger.warn(
            { userId: msg.user_id, targetJid: msg.target_jid, msgId: msg.msg_id },
            'Target user not connected, cannot deliver outbound message',
          );
        }
      } else {
        // Legacy fallback: try all connected users
        const connectedIds = manager.listConnected();
        for (const userId of connectedIds) {
          const client = manager.getClient(userId);
          if (!client || !client.isConnected()) continue;

          try {
            const prefix = msg.skip_prefix || ASSISTANT_HAS_OWN_NUMBER ? '' : `${ASSISTANT_NAME}: `;
            await client.sendMessage(msg.target_jid, `${prefix}${msg.message}`);
            await bridge.ackOutbound(msg.msg_id);
            logger.info(
              { userId, targetJid: msg.target_jid, msgId: msg.msg_id },
              'Outbound cron message delivered (legacy fallback)',
            );
            delivered = true;
            break;
          } catch (err) {
            logger.error(
              { userId, targetJid: msg.target_jid, msgId: msg.msg_id, err },
              'Failed to deliver outbound message via user',
            );
          }
        }

        if (!delivered && connectedIds.length > 0) {
          logger.warn(
            { targetJid: msg.target_jid, msgId: msg.msg_id },
            'Outbound message could not be delivered by any connected user',
          );
        }
      }
    }
  } catch (err) {
    logger.debug({ err }, 'Outbound poll error (will retry)');
  }
}

async function main(): Promise<void> {
  initDatabase();
  logger.info('Database initialized');

  // Verify Flask is reachable before starting
  try {
    await bridge.login();
  } catch (err) {
    logger.fatal({ err }, 'Cannot connect to Flask server — is it running?');
    process.exit(1);
  }

  const manager = new ConnectionManager((userId, msg) => {
    handleMessage(userId, msg, manager).catch((err) =>
      logger.error({ userId, err }, 'Unhandled error in handleMessage'),
    );
  });

  // Restore previously linked WhatsApp sessions
  await manager.restoreAll();
  logger.info('Session restore complete');

  // Start the internal REST API for connection management
  startApiServer(manager);

  // Graceful shutdown
  let outboundTimer: ReturnType<typeof setInterval> | null = null;
  const shutdown = async (signal: string) => {
    logger.info({ signal }, 'Shutting down');
    if (outboundTimer) clearInterval(outboundTimer);
    const connected = manager.listConnected();
    for (const userId of connected) {
      try {
        await manager.disconnect(userId);
      } catch { /* best effort */ }
    }
    process.exit(0);
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));

  // Start polling for outbound cron job messages every 5 seconds
  outboundTimer = setInterval(() => {
    if (manager.listConnected().length > 0) {
      pollOutboundMessages(manager).catch((err) =>
        logger.error({ err }, 'Unhandled outbound poll error'),
      );
    }
  }, 5000);
  logger.info('DREAM-Chat WhatsApp bridge is running (multi-user mode)');
  logger.info('Outbound message polling started (5s interval)');
}

main().catch((err) => {
  logger.fatal({ err }, 'Fatal startup error');
  process.exit(1);
});

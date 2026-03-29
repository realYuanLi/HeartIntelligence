import express, { Request, Response, NextFunction } from 'express';
import QRCode from 'qrcode';

import { NODE_API_KEY, NODE_API_PORT } from './config.js';
import { ConnectionManager } from './connection-manager.js';
import { logger } from './logger.js';

/**
 * API key authentication middleware.
 * Skips auth if NODE_API_KEY is not configured (development convenience),
 * but logs a warning per-request.
 */
function apiKeyAuth(req: Request, res: Response, next: NextFunction): void {
  if (!NODE_API_KEY) {
    logger.warn(
      { method: req.method, path: req.path },
      'NODE_API_KEY is empty — allowing unauthenticated request (dev mode)',
    );
    next();
    return;
  }
  const key = req.headers['x-api-key'];
  if (key !== NODE_API_KEY) {
    res.status(401).json({ success: false, message: 'Unauthorized' });
    return;
  }
  next();
}

/**
 * Start the Express REST API server for managing WhatsApp connections.
 * All endpoints are internal-only (not exposed to the internet).
 */
export function startApiServer(manager: ConnectionManager): void {
  if (!NODE_API_KEY) {
    logger.warn('NODE_API_KEY is not set — API authentication is disabled (dev mode)');
  }

  const app = express();
  app.use(express.json());
  app.use(apiKeyAuth);

  // ── Health check ──────────────────────────────────────────────────────────

  app.get('/api/health', (_req: Request, res: Response) => {
    res.json({
      ok: true,
      uptime: process.uptime(),
      connections: manager.listConnected().length,
    });
  });

  // ── List all connections ──────────────────────────────────────────────────

  app.get('/api/connections', (_req: Request, res: Response) => {
    const connections = manager.listAll();
    res.json({ success: true, connections });
  });

  // ── Connect a user ────────────────────────────────────────────────────────

  app.post('/api/connections/:userId/connect', async (req: Request, res: Response) => {
    const userId = parseInt(String(req.params.userId), 10);
    if (isNaN(userId)) {
      res.status(400).json({ success: false, message: 'Invalid userId' });
      return;
    }

    try {
      // Start connection in the background; don't await full connect
      // (which waits for 'open'). The client will report status via getStatus().
      const status = manager.getStatus(userId);
      if (status.status === 'connected' || status.status === 'qr' || status.status === 'connecting') {
        res.status(409).json({ success: false, message: 'Already connected' });
        return;
      }

      // Fire and forget: connect runs async, user polls status
      manager.connect(userId).catch((err) => {
        logger.error({ userId, err }, 'Connection failed');
      });

      res.json({ success: true, status: 'connecting' });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      logger.error({ userId, err }, 'Failed to initiate connection');
      res.status(500).json({ success: false, message });
    }
  });

  // ── Disconnect a user ─────────────────────────────────────────────────────

  app.post('/api/connections/:userId/disconnect', async (req: Request, res: Response) => {
    const userId = parseInt(String(req.params.userId), 10);
    if (isNaN(userId)) {
      res.status(400).json({ success: false, message: 'Invalid userId' });
      return;
    }

    try {
      await manager.disconnect(userId);
      res.json({ success: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      if (message === 'No active connection') {
        res.status(404).json({ success: false, message });
      } else {
        res.status(500).json({ success: false, message });
      }
    }
  });

  // ── Get connection status ─────────────────────────────────────────────────

  app.get('/api/connections/:userId/status', async (req: Request, res: Response) => {
    const userId = parseInt(String(req.params.userId), 10);
    if (isNaN(userId)) {
      res.status(400).json({ success: false, message: 'Invalid userId' });
      return;
    }

    const info = manager.getStatus(userId);
    let qrDataUrl: string | null = null;

    if (info.qr) {
      try {
        qrDataUrl = await QRCode.toDataURL(info.qr, { width: 300, margin: 2 });
      } catch (err) {
        logger.warn({ userId, err }, 'Failed to generate QR data URL');
      }
    }

    res.json({
      success: true,
      status: info.status,
      phoneNumber: info.phoneNumber,
      qrDataUrl,
    });
  });

  // ── QR code SSE stream ────────────────────────────────────────────────────

  app.get('/api/connections/:userId/qr-stream', async (req: Request, res: Response) => {
    const userId = parseInt(String(req.params.userId), 10);
    if (isNaN(userId)) {
      res.status(400).json({ success: false, message: 'Invalid userId' });
      return;
    }

    // Set SSE headers
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();

    // Helper to send an SSE event
    function sendEvent(event: string, data: Record<string, unknown>): void {
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    }

    // Send current status immediately
    const info = manager.getStatus(userId);
    if (info.status === 'qr' && info.qr) {
      try {
        const qrDataUrl = await QRCode.toDataURL(info.qr, { width: 300, margin: 2 });
        sendEvent('qr', { qr_data_url: qrDataUrl });
      } catch {
        sendEvent('status', { status: info.status });
      }
    } else if (info.status === 'connected') {
      sendEvent('status', { status: 'connected', phone_number: info.phoneNumber });
    } else {
      sendEvent('status', { status: info.status });
    }

    // Subscribe to real-time updates from the WhatsApp client.
    // The client may not exist yet if /connect was just called and the
    // ConnectionManager hasn't finished creating it.  Wait briefly for it
    // to appear so SSE listeners can be attached.
    let client = manager.getClient(userId);
    if (!client) {
      // Poll up to 5 seconds (50 x 100ms) for the client to appear
      for (let i = 0; i < 50 && !client; i++) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        client = manager.getClient(userId);
      }
    }

    let unsubStatus: (() => void) | null = null;
    let unsubQr: (() => void) | null = null;

    if (client) {
      unsubQr = client.onQrChange(async (qr) => {
        if (qr) {
          try {
            const qrDataUrl = await QRCode.toDataURL(qr, { width: 300, margin: 2 });
            sendEvent('qr', { qr_data_url: qrDataUrl });
          } catch {
            sendEvent('status', { status: 'qr' });
          }
        }
      });

      unsubStatus = client.onStatusChange((status, phoneNumber) => {
        if (status === 'connected') {
          sendEvent('status', { status: 'connected', phone_number: phoneNumber });
          // Close stream once connected — client no longer needs updates
          cleanup();
          res.end();
        } else {
          sendEvent('status', { status });
        }
      });
    } else {
      // Client never appeared — inform the caller
      sendEvent('status', { status: 'disconnected', warning: 'Connection not started. Call /connect first.' });
    }

    // Keep-alive ping every 15 seconds to prevent proxy timeouts
    const keepAlive = setInterval(() => {
      res.write(': ping\n\n');
    }, 15000);

    function cleanup(): void {
      clearInterval(keepAlive);
      if (unsubStatus) { unsubStatus(); unsubStatus = null; }
      if (unsubQr) { unsubQr(); unsubQr = null; }
    }

    // Clean up on client disconnect
    req.on('close', cleanup);
  });

  // ── Start server ──────────────────────────────────────────────────────────

  app.listen(NODE_API_PORT, () => {
    logger.info({ port: NODE_API_PORT }, 'WhatsApp API server listening');
  });
}

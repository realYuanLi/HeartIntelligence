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

  // ── Start server ──────────────────────────────────────────────────────────

  app.listen(NODE_API_PORT, () => {
    logger.info({ port: NODE_API_PORT }, 'WhatsApp API server listening');
  });
}

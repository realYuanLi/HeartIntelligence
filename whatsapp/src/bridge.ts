import { BOT_EMAIL, getBotPassword, clearBotPasswordCache, FLASK_BASE_URL } from './config.js';
import { logger } from './logger.js';

/**
 * Manages an authenticated session with the DREAM-Chat Flask server.
 * Handles login, session cookie persistence, and message forwarding.
 */
export class FlaskBridge {
  // Cookie header value from the last successful login
  private sessionCookie: string | null = null;

  /**
   * Log in to the Flask server and store the session cookie.
   * Throws if login fails.
   */
  async login(): Promise<void> {
    // Clear cached password so we re-read from .bot_secret on disk,
    // which may have been regenerated after a Flask restart.
    clearBotPasswordCache();

    const res = await fetch(`${FLASK_BASE_URL}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: BOT_EMAIL, password: getBotPassword() }),
    });

    if (!res.ok) {
      throw new Error(`Flask login failed: HTTP ${res.status}`);
    }

    const body = (await res.json()) as { success: boolean; message?: string };
    if (!body.success) {
      throw new Error(`Flask login rejected: ${body.message ?? 'unknown'}`);
    }

    // Persist the Set-Cookie header for subsequent requests
    const setCookie = res.headers.get('set-cookie');
    if (setCookie) {
      // Extract just the session token (strip attributes like Path, HttpOnly, etc.)
      this.sessionCookie = setCookie.split(';')[0];
    }

    logger.info({ email: BOT_EMAIL }, 'Logged in to Flask server');
  }

  /**
   * Ensure we have a valid session, logging in if necessary.
   */
  private async ensureSession(): Promise<void> {
    if (!this.sessionCookie) {
      await this.login();
    }
  }

  /**
   * Create a new chat session in Flask and return its session_id.
   */
  async createSession(): Promise<string> {
    await this.ensureSession();

    const res = await fetch(`${FLASK_BASE_URL}/api/new_session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: this.sessionCookie!,
      },
    });

    if (res.status === 401) {
      // Session expired — re-login and retry once
      this.sessionCookie = null;
      await this.login();
      return this.createSession();
    }

    if (!res.ok) {
      throw new Error(`Failed to create Flask session: HTTP ${res.status}`);
    }

    const body = (await res.json()) as { success: boolean; session_id?: string };
    if (!body.success || !body.session_id) {
      throw new Error('Flask did not return a session_id');
    }

    logger.debug({ sessionId: body.session_id }, 'Created Flask session');
    return body.session_id;
  }

  /**
   * Send a user message to an existing Flask session and return the assistant reply.
   * Automatically re-authenticates on 401 and retries once.
   */
  async sendMessage(flaskSessionId: string, text: string): Promise<string> {
    await this.ensureSession();

    const reply = await this.doSendMessage(flaskSessionId, text);
    return reply;
  }

  private async doSendMessage(
    flaskSessionId: string,
    text: string,
    retried = false,
  ): Promise<string> {
    const res = await fetch(`${FLASK_BASE_URL}/api/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: this.sessionCookie!,
      },
      body: JSON.stringify({ session_id: flaskSessionId, message: text }),
    });

    if (res.status === 401 && !retried) {
      this.sessionCookie = null;
      await this.login();
      return this.doSendMessage(flaskSessionId, text, true);
    }

    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as {
        assistant_message?: string;
      };
      throw new Error(
        body.assistant_message ?? `Flask /api/message returned HTTP ${res.status}`,
      );
    }

    const body = (await res.json()) as {
      success: boolean;
      assistant_message?: string;
    };

    if (!body.assistant_message) {
      throw new Error('Flask returned no assistant_message');
    }

    return body.assistant_message;
  }

  /**
   * Send a WhatsApp user's message via the dedicated /api/whatsapp/message
   * endpoint.  Flask manages the session mapping (sender_jid → session_id)
   * so the bridge no longer needs to track it locally.
   *
   * Automatically re-authenticates on 401 and retries once.
   */
  async sendWhatsAppMessage(
    senderJid: string,
    senderName: string,
    text: string,
    images?: string[],
    userId?: number,
  ): Promise<{ reply: string; exerciseImages: Array<{ name: string; url: string; level?: string; equipment?: string; muscles?: string }> }> {
    await this.ensureSession();
    return this.doSendWhatsAppMessage(senderJid, senderName, text, images, userId);
  }

  private async doSendWhatsAppMessage(
    senderJid: string,
    senderName: string,
    text: string,
    images?: string[],
    userId?: number,
    retried = false,
  ): Promise<{ reply: string; exerciseImages: Array<{ name: string; url: string; level?: string; equipment?: string; muscles?: string }> }> {
    const payload: Record<string, unknown> = {
      sender_jid: senderJid,
      sender_name: senderName,
      message: text,
    };
    if (images && images.length > 0) payload.images = images;
    if (userId !== undefined) payload.user_id = userId;

    const res = await fetch(`${FLASK_BASE_URL}/api/whatsapp/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: this.sessionCookie!,
      },
      body: JSON.stringify(payload),
    });

    if (res.status === 401 && !retried) {
      this.sessionCookie = null;
      await this.login();
      return this.doSendWhatsAppMessage(senderJid, senderName, text, images, userId, true);
    }

    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as {
        message?: string;
        assistant_message?: string;
      };
      throw new Error(
        body.assistant_message ??
          body.message ??
          `Flask /api/whatsapp/message returned HTTP ${res.status}`,
      );
    }

    const body = (await res.json()) as {
      success: boolean;
      assistant_message?: string;
      session_id?: string;
      exercise_images?: Array<{ name: string; url: string; level?: string; equipment?: string; muscles?: string }>;
    };

    if (!body.assistant_message) {
      throw new Error('Flask returned no assistant_message');
    }

    return {
      reply: body.assistant_message,
      exerciseImages: body.exercise_images ?? [],
    };
  }

  /**
   * Fetch an exercise image from the Flask server and return it as a Buffer.
   */
  async fetchExerciseImage(imageUrl: string): Promise<Buffer> {
    await this.ensureSession();

    const url = imageUrl.startsWith('http') ? imageUrl : `${FLASK_BASE_URL}${imageUrl}`;
    const res = await fetch(url, {
      headers: { Cookie: this.sessionCookie! },
    });

    if (!res.ok) {
      throw new Error(`Failed to fetch exercise image: HTTP ${res.status}`);
    }

    const arrayBuffer = await res.arrayBuffer();
    return Buffer.from(arrayBuffer);
  }

  /**
   * Poll Flask for pending outbound messages (cron job deliveries).
   * Returns an array of messages to send, each with msg_id, target_jid, and message.
   */
  async pollOutbound(): Promise<
    Array<{ msg_id: string; target_jid: string; message: string; skip_prefix?: boolean; user_id?: number }>
  > {
    await this.ensureSession();
    return this.doPollOutbound();
  }

  private async doPollOutbound(
    retried = false,
  ): Promise<Array<{ msg_id: string; target_jid: string; message: string; skip_prefix?: boolean; user_id?: number }>> {
    const res = await fetch(`${FLASK_BASE_URL}/api/whatsapp/outbound`, {
      headers: {
        Cookie: this.sessionCookie!,
      },
    });

    if (res.status === 401 && !retried) {
      this.sessionCookie = null;
      await this.login();
      return this.doPollOutbound(true);
    }

    if (!res.ok) return [];

    const body = (await res.json()) as {
      success: boolean;
      messages?: Array<{ msg_id: string; target_jid: string; message: string; skip_prefix?: boolean; user_id?: number }>;
    };

    return body.messages ?? [];
  }

  /**
   * Acknowledge delivery of an outbound message so Flask marks it as delivered.
   */
  async ackOutbound(msgId: string): Promise<void> {
    await this.ensureSession();
    await this.doAckOutbound(msgId);
  }

  private async doAckOutbound(msgId: string, retried = false): Promise<void> {
    const res = await fetch(`${FLASK_BASE_URL}/api/whatsapp/outbound/${msgId}/ack`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: this.sessionCookie!,
      },
    });

    if (res.status === 401 && !retried) {
      this.sessionCookie = null;
      await this.login();
      return this.doAckOutbound(msgId, true);
    }
  }
}

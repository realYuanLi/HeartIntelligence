import { FLASK_BASE_URL, FLASK_PASSWORD, FLASK_USERNAME } from './config.js';
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
    const res = await fetch(`${FLASK_BASE_URL}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: FLASK_USERNAME, password: FLASK_PASSWORD }),
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

    logger.info({ username: FLASK_USERNAME }, 'Logged in to Flask server');
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
}

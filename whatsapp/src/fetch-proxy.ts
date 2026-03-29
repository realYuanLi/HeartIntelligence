/**
 * Monkey-patch globalThis.fetch to route HTTP/HTTPS requests through the
 * configured SOCKS5 or HTTP proxy.
 *
 * Baileys uses native fetch() for media uploads (POST with a Readable body,
 * duplex:'half', AbortSignal) and downloads (GET, expects response.body as
 * ReadableStream).  Node 24's built-in fetch ignores userland undici
 * dispatchers set via setGlobalDispatcher, so we replace globalThis.fetch
 * entirely with a wrapper that pipes requests through node:http(s) using
 * SocksProxyAgent / HttpsProxyAgent.
 *
 * Must be called once at startup, before any fetch() calls.
 */

import http from 'node:http';
import https from 'node:https';
import { Readable } from 'node:stream';

import { SocksProxyAgent } from 'socks-proxy-agent';
import { HttpsProxyAgent } from 'https-proxy-agent';

import { WA_PROXY_URL } from './config.js';
import { logger } from './logger.js';

export async function setupFetchProxy(): Promise<void> {
  if (!WA_PROXY_URL) return;

  let url: URL;
  try {
    url = new URL(WA_PROXY_URL);
  } catch {
    logger.warn({ proxy: WA_PROXY_URL }, 'Invalid proxy URL, skipping fetch proxy setup');
    return;
  }

  const isSocks = url.protocol === 'socks5:' || url.protocol === 'socks5h:';
  const isHttp = url.protocol === 'http:' || url.protocol === 'https:';

  if (!isSocks && !isHttp) {
    logger.warn({ proxy: WA_PROXY_URL }, 'Unsupported proxy protocol for fetch');
    return;
  }

  const agent: http.Agent = isSocks
    ? new SocksProxyAgent(WA_PROXY_URL)
    : new HttpsProxyAgent(WA_PROXY_URL);

  const originalFetch = globalThis.fetch;

  /**
   * Convert the `body` value from a fetch() call into something that
   * node:http .request() can consume (string | Buffer | Readable).
   */
  function normalizeBody(
    body: BodyInit | null | undefined,
  ): string | Buffer | Readable | undefined {
    if (body == null) return undefined;
    if (typeof body === 'string') return body;
    if (Buffer.isBuffer(body)) return body;
    if (body instanceof Uint8Array) return Buffer.from(body);
    if (body instanceof ArrayBuffer) return Buffer.from(body);
    // Node.js Readable stream (e.g. fs.createReadStream from Baileys uploads)
    if (body instanceof Readable) return body;
    // Web ReadableStream → convert to Node Readable
    if (typeof ReadableStream !== 'undefined' && body instanceof ReadableStream) {
      return Readable.fromWeb(body as import('stream/web').ReadableStream);
    }
    // URLSearchParams, FormData — fall back to toString
    if (typeof body.toString === 'function') return body.toString();
    return undefined;
  }

  /**
   * Flatten a Headers / Record / [string,string][] into a plain object
   * suitable for node:http request options.
   */
  function flattenHeaders(
    headers: HeadersInit | undefined,
  ): Record<string, string> {
    if (!headers) return {};
    if (Array.isArray(headers)) {
      return Object.fromEntries(headers);
    }
    if (typeof (headers as Headers).entries === 'function') {
      const out: Record<string, string> = {};
      for (const [k, v] of (headers as Headers).entries()) {
        out[k] = v;
      }
      return out;
    }
    // plain object
    return headers as Record<string, string>;
  }

  const patchedFetch: typeof globalThis.fetch = function patchedFetch(
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> {
    // Determine the target URL string.
    let targetUrl: string;
    if (typeof input === 'string') {
      targetUrl = input;
    } else if (input instanceof URL) {
      targetUrl = input.toString();
    } else if (input instanceof Request) {
      targetUrl = input.url;
    } else {
      // Unknown input — delegate to original fetch.
      return originalFetch(input, init);
    }

    // Only proxy http/https requests.  Everything else (data:, blob:, or
    // relative URLs used internally) goes through the original fetch.
    let parsed: URL;
    try {
      parsed = new URL(targetUrl);
    } catch {
      return originalFetch(input, init);
    }

    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return originalFetch(input, init);
    }

    // Skip proxy for local/loopback addresses (e.g. Flask at localhost:8000)
    const host = parsed.hostname;
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '0.0.0.0') {
      return originalFetch(input, init);
    }

    // Build the node:http(s) request.
    const method = init?.method ?? (input instanceof Request ? input.method : 'GET');
    const reqHeaders = flattenHeaders(init?.headers ?? (input instanceof Request ? Object.fromEntries(input.headers.entries()) : undefined));
    const body = normalizeBody(init?.body ?? undefined);
    const isSecure = parsed.protocol === 'https:';
    const transport = isSecure ? https : http;

    return new Promise<Response>((resolve, reject) => {
      const reqOpts: https.RequestOptions = {
        hostname: parsed.hostname,
        port: parsed.port || (isSecure ? 443 : 80),
        path: parsed.pathname + parsed.search,
        method,
        headers: reqHeaders,
        agent,
      };

      const signal = init?.signal as AbortSignal | undefined;
      if (signal?.aborted) {
        reject(new DOMException('The operation was aborted.', 'AbortError'));
        return;
      }

      const req = transport.request(reqOpts, (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (chunk: Buffer) => chunks.push(chunk));
        res.on('end', () => {
          const responseBuffer = Buffer.concat(chunks);

          // Build a headers object for the Response constructor.
          const resHeaders: Record<string, string> = {};
          for (const [key, val] of Object.entries(res.headers)) {
            if (val != null) {
              resHeaders[key] = Array.isArray(val) ? val.join(', ') : val;
            }
          }

          // Construct a spec-compliant Response.
          // `new Response(buffer)` produces a ReadableStream body, which
          // Baileys consumes via `Readable.fromWeb(response.body)`.
          const response = new Response(responseBuffer, {
            status: res.statusCode ?? 200,
            statusText: res.statusMessage ?? '',
            headers: resHeaders,
          });

          resolve(response);
        });
        res.on('error', (err) => reject(err));
      });

      // Wire up AbortSignal.
      if (signal) {
        const onAbort = () => {
          req.destroy(new DOMException('The operation was aborted.', 'AbortError'));
        };
        signal.addEventListener('abort', onAbort, { once: true });
        req.on('close', () => signal.removeEventListener('abort', onAbort));
      }

      req.on('error', (err) => reject(err));

      // Write the body.
      if (body instanceof Readable) {
        body.pipe(req);
      } else if (body != null) {
        req.end(body);
      } else {
        req.end();
      }
    });
  };

  globalThis.fetch = patchedFetch;
  logger.info(
    { proxy: WA_PROXY_URL, type: isSocks ? 'SOCKS5' : 'HTTP' },
    'Global fetch monkey-patched to route through proxy',
  );
}

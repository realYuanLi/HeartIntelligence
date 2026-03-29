# Fix: SOCKS5 Proxy for Baileys Media Uploads
**Date**: 2026-03-28  |  **Status**: Completed

## What Was Built
Rewrote the fetch proxy module to monkey-patch `globalThis.fetch` so Baileys' media uploads (images, video, documents) work through a SOCKS5 proxy. Previously, text messages worked (WebSocket uses proxy agent directly) but media uploads failed because Node 24's built-in `fetch()` ignores both SOCKS5 env vars and `undici.setGlobalDispatcher()`.

## Architecture
```
Baileys sendMessage({image: buffer})
  -> generateWAMessage -> prepareWAMessageMedia -> upload()
    -> fetch(cdnUrl, {method:'POST', body: createReadStream(...)})
      -> [monkey-patched] globalThis.fetch
        -> node:https.request + SocksProxyAgent -> SOCKS5 tunnel -> WhatsApp CDN
```

## Key Files
| File | Purpose |
|------|---------|
| `whatsapp/src/fetch-proxy.ts` | Monkey-patches `globalThis.fetch` with SOCKS5/HTTP proxy routing |
| `whatsapp/src/index.ts` | Calls `setupFetchProxy()` at startup before any connections |

## Technical Decisions
- **Monkey-patch globalThis.fetch** instead of `setGlobalDispatcher`: Node 24's internal undici ignores userland dispatchers. Patching `globalThis.fetch` is the only reliable interception point.
- **node:https + SocksProxyAgent** for the actual requests: Avoids undici entirely. `socks-proxy-agent` handles SOCKS5 tunneling, `https-proxy-agent` for HTTP proxies.
- **Full response buffering**: Response bodies are collected into a Buffer then wrapped in `new Response(buffer)`. Acceptable for WhatsApp's media size limits (max ~100MB).
- **Stream body support**: Baileys passes `fs.createReadStream()` as body; the patched fetch detects `Readable` instances and pipes them directly into the proxy tunnel.

## Usage
Set `WA_PROXY_URL=socks5://127.0.0.1:7897` in `whatsapp/.env`. On startup, the log shows:
```
Global fetch monkey-patched to route through proxy
```

## Known Limitations
- Response bodies are fully buffered in memory (no streaming). Fine for typical WhatsApp media but could use ~100MB for large documents.
- All HTTP/HTTPS fetch calls go through the proxy (no selective hostname filtering).

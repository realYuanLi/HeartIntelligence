# Mobile Responsive UI Layer
**Date**: 2026-04-07  |  **Status**: Completed

## What Was Built
A purely additive mobile responsive layer for the Health Pal Flask app. At viewport widths <=768px, the primary and secondary sidebars become an off-canvas drawer triggered by a fixed hamburger button, while main content, chat input, and per-page layouts reflow to fit phone screens. Desktop renders are pixel-identical because the new chrome is hidden outside the media query. End users on phones can now actually navigate and chat without horizontal scrolling.

## Architecture
A single hamburger button + dimming backdrop are injected once into `base.html`. CSS appends one `@media (max-width: 768px)` block that pins both sidebars to `position: fixed` with `transform: translateX(-100%)`, then slides them in when `body.mobile-nav-open` is set. `display: flex !important` is required because an existing `@media (max-width: 1200px)` rule already hides the sidebars; we need to beat it without editing it. A self-contained IIFE in `script.js` toggles the body class, closes on backdrop tap or sidebar item click, and resets when `matchMedia` reports a return to desktop width.

## Key Files
| File | Purpose |
| --- | --- |
| `templates/base.html` (lines 13-16) | Hamburger button + backdrop element |
| `static/style.css` (lines 7733-7996) | Mobile media query block (~264 lines) |
| `static/script.js` (lines 2277-2310) | Drawer toggle IIFE |

## Technical Decisions
- **Single 768px breakpoint**: phones only; the 769-1200px tablet gap retains pre-existing behavior to avoid disturbing desktop.
- **Off-canvas drawer over bottom nav**: preserves the existing two-tier (primary + secondary) sidebar structure without duplicating navigation markup.
- **`!important` on sidebar `display`**: the existing 1200px-and-below rule sets `display: none`; overriding it without editing the original rule keeps the diff additive.
- **`font-size: 16px` on `.message-input`**: iOS Safari auto-zooms when focusing inputs under 16px; setting it exactly to 16px prevents the zoom-and-pan jump.
- **Self-contained IIFE**: avoids touching the existing 2275-line script, guards on missing elements, and is a no-op on desktop via `matchMedia`.

## Usage
```bash
# Serve the app and emulate a phone
python app.py
# Open http://localhost:5000 in Chrome
# DevTools (Cmd+Opt+I) > Toggle device toolbar (Cmd+Shift+M) > iPhone 12 Pro
# Or visit from a phone on the same LAN: http://<your-ip>:5000
```

## Testing
`python -m pytest tests/` runs the backend suite. CSS and JS pass `node --check` and brace-balance checks. 872 backend tests pass; the 62 pre-existing failures are unrelated (verified against a clean tree).

## Known Limitations
- Tablet gap 769-1200px keeps the pre-existing hidden-sidebar behavior with no replacement (out of scope; preserves desktop).
- `login.html` / `register.html` don't extend `base.html` so they have no hamburger, but they don't need one (no sidebar).
- Right-side panels (sources, health-info) remain 400px wide and may exceed narrow phone viewports.

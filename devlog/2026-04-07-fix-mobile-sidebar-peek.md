# Fix: Mobile sidebar 76px peek
**Date**: 2026-04-07  |  **Status**: Completed

## What Was Built
A two-rule CSS fix that makes the secondary sidebar fully withdraw off-canvas on mobile (≤768px). Before the fix, a 76px-wide opaque white strip remained visible at the left edge of the screen when the drawer was closed — the user described this as "the left bar did not fully withdraw."

## Root Cause
The first mobile pass set `.secondary-sidebar { left: 76px; transform: translateX(-100%) }` inside `@media (max-width: 768px)`. The intent was for the secondary sidebar to slide off the left edge. The bug: `translateX(-100%)` translates by **the element's own width** (236px), not 100% of the viewport. With a starting `left: 76px`, the resting bounding box becomes `[76 - 236, 312 - 236] = [-160, 76]`. The right edge sits at x = **76px**, leaving a 76px-wide opaque white strip pinned to the left of the screen, on top of `main` content (z-index 1001).

## The Fix
Two new rules appended to the END of the existing `@media (max-width: 768px)` block in `static/style.css`. Source-order cascade lets them override only the `left` declaration of the existing rules without touching the `transform` (which still drives the slide animation):

```css
.secondary-sidebar { left: 0; }                                              /* rest */
body.mobile-nav-open .secondary-sidebar:not([style*="display: none"]):not([style*="display:none"]) {
  left: 76px;                                                                /* open */
}
```

## Pixel Math (post-fix, viewport 375px)
| State | Primary | Secondary |
|---|---|---|
| Closed | `[-76, 0]` (off) | `[-236, 0]` (off) |
| Open (chat/dashboard/etc.) | `[0, 76]` | `[76, 312]` |
| Open (family/community, inline `display:none`) | `[0, 76]` | excluded by `:not()`, stays off-canvas |
| Desktop ≥769px | unchanged | unchanged |

## Key Files
| File | Purpose |
|---|---|
| `static/style.css` (lines ~8267–8279) | The 14-line additive fix block (1 blank, comment, 2 rules) |

## Technical Decisions
- **Why source-order override instead of editing the existing rule:** Preserves the "additive only" invariant from the previous mobile passes and keeps the diff trivially small (and trivially revertable). The new `left: 0` rule has identical specificity to the existing `left: 76px` rule but appears later, so the cascade picks it.
- **Why two rules instead of one:** The closed state needs `left: 0`; the open state needs `left: 76px`. They are mutually exclusive via the `body.mobile-nav-open` class.
- **Why the same `:not([style*="display: none"])` filter on the open-state rule:** Mirrors the existing transform rule's filter. On family/community pages, an inline `style="display: none"` is set on the secondary sidebar by JS — the `:not()` keeps the secondary sidebar off-canvas in the open state too, so only the primary slides in. Without the filter, the secondary would slide in showing an empty panel.
- **Why no JS/template change:** The drawer-toggle IIFE only flips a body class. The bug was purely CSS positioning; no JS contract changed.

## Verification
- Brace balance: 1317 / 1317
- Source-order winner verified via direct file read at lines 7795–7820 (existing) and 8267–8279 (new)
- Flask test client `GET /static/style.css` → 200, marker present
- All 4 viewport/state permutations produce the correct geometry on paper

## Usage
Test on a phone or DevTools mobile emulation at 375×667:
1. Visit any page with a secondary sidebar (`/`, `/dashboard`, `/calendar`, `/tools/live-video`)
2. Confirm: no white strip on the left edge
3. Tap the hamburger top-left → both sidebars slide in flush
4. Tap the backdrop or any nav item → both slide out fully

## Known Limitations
None for this fix. It's a 14-line additive change that resolves the specific peek bug without affecting any other state.

# Fix: Mobile toggle dead zone (769–1200px)
**Date**: 2026-04-07  |  **Status**: Completed

## What Was Built
A 74-line additive CSS block that exposes the hamburger toggle and off-canvas drawer in the **769px–1200px viewport range**. Before this fix, that range was a navigation dead zone: an existing `@media (max-width: 1200px)` rule hid both sidebars, while the mobile drawer rules only activated at `≤768px`. Users on tablets, small laptops, and resized browser windows in this range had no visible navigation chrome at all.

## Root Cause
| Width | Sidebars | Toggle | Net nav |
|---|---|---|---|
| ≥1201px | visible | hidden | sidebars ✓ |
| **769–1200px** | **hidden** (existing 1200px rule) | **hidden** (default) | **NONE — BUG** |
| ≤768px | off-canvas drawer | visible | toggle + drawer ✓ |

The first mobile pass (`de43e23`) only enabled the toggle and drawer rules inside `@media (max-width: 768px)`. The pre-existing `@media (max-width: 1200px) { .primary-sidebar, .secondary-sidebar { display: none } }` rule starts hiding sidebars at 1200px, creating a 432-pixel-wide gap (769–1200) where neither system was active.

## The Fix
Append a NEW media query block at the very end of `static/style.css` (line 8322):

```css
@media (min-width: 769px) and (max-width: 1200px) {
  .mobile-nav-toggle      { display: flex; ... }              /* same look as ≤768px */
  .mobile-nav-backdrop    { display: none; ... }
  body.mobile-nav-open .mobile-nav-backdrop { display: block; }
  .primary-sidebar        { display: flex !important; position: fixed; left: 0; transform: translateX(-100%); ... }
  .secondary-sidebar      { display: flex !important; position: fixed; left: 0; transform: translateX(-100%); ... }
  body.mobile-nav-open .primary-sidebar { transform: translateX(0); }
  body.mobile-nav-open .secondary-sidebar:not([style*="display: none"]):not([style*="display:none"]) {
    transform: translateX(0);
    left: 76px;
  }
}
```

The new block reuses the same toggle look, drawer geometry, and `:not()` exclusion pattern as the existing ≤768px block. The `secondary-sidebar` uses the same `left: 0` at rest + `left: 76px` when open pattern as commit `5d46451` to avoid the 76px peek bug.

## Why This Is Surgical
- **Only navigation chrome is added.** No `body { display }`, `main`, chat input, message bubble, or page header rules — page content layout in 769–1200px keeps its current rendering. The drawer is purely an overlay.
- **No existing rule modified.** Both the `@media (max-width: 1200px)` sidebar-hide rule and the `@media (max-width: 768px)` mobile block are byte-identical to before.
- **No JS or template change.** The existing IIFE in `static/script.js` flips `body.mobile-nav-open` based on toggle and backdrop clicks, neither of which is breakpoint-gated, so it works at any viewport width without modification.
- **Desktop ≥1201px is untouched.** The new media query doesn't fire at 1280px, so sidebars stay at default `display: flex` and the toggle stays at default `display: none`.

## Key Files
| File | Purpose |
|---|---|
| `static/style.css` (lines 8322–8395) | The 74-line additive `@media (min-width: 769px) and (max-width: 1200px)` block |

## Verification
- Brace balance: 1325 / 1325
- Coverage walkthrough: at 1280, 1201, 1200, 1100, 900, 800, 769, 768, 320 — all states behave correctly
- Pixel math at 1000px: closed primary `[-76, 0]`, closed secondary `[-236, 0]` (both off-canvas); open primary `[0, 76]`, open secondary `[76, 312]` (flush)
- Family/community at 1000px: secondary excluded by `:not()`, only primary slides in
- Flask test client `GET /static/style.css` → 200, marker present
- `git diff -U0 static/style.css` confirms the only new change is a single 74-line append at line 8322; no edits inside the existing 768px or 1200px blocks

## How to Verify
1. Resize a browser window from 1300px down to 320px slowly. The hamburger should appear at 1200px (not 768px) and stay visible all the way down to 320px.
2. At any width in 769–1200px, the hamburger top-left should be visible. Tap it → both sidebars slide in from the left.
3. Tap the backdrop or any nav item → drawer closes.
4. At ≥1201px, no hamburger; sidebars are visible at their normal desktop position (unchanged from before).

## Known Minor UX Notes
- The existing JS `if (mq.matches) close()` for sidebar-item-click auto-close is gated by `(max-width: 768px)`, so in 769–1200px tapping a nav item doesn't auto-close the drawer. However, the nav item navigates via `<a>` link and the new page load resets `body`, so the drawer is effectively closed on the next page anyway. Users can also close manually via backdrop tap or hamburger tap. Acceptable; no JS change made.
- Auth pages (`login.html`, `register.html`) don't extend `base.html` and have no sidebar to drawer — the toggle is not rendered there. Out of scope.

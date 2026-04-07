# Mobile Audit & Fix Pass
**Date**: 2026-04-07  |  **Status**: Completed

## What Was Built
A second, audit-driven mobile responsive pass building on commit `de43e23`. Purely additive CSS — no template, JS, or Python touched. Closes gaps in safe-area handling, sticky-header hamburger clearance, iOS auto-zoom, touch targets, long-text wrapping, and per-page layout glitches across Welcome, Dashboard, Nutrition, Cron Jobs, Calendar, Family, Community, PDF Forms, Live Video, Auth, and Chat.

## Architecture
The fix layer lives entirely inside the existing `@media (max-width: 768px)` block in `static/style.css` (lines 8000–8265, ~265 new lines), placed at the END of the block so source-order cascade lets it override prior desktop and same-block mobile rules without bumping specificity. A second, brand-new `@media (max-width: 360px)` block (lines 8273–8307) handles ultra-small phones (iPhone SE 1st gen) with even tighter typography and padding. Both blocks are additive; nothing earlier in the file was edited.

## Key Changes
| Area | Change |
| --- | --- |
| Safe area | `overscroll-behavior-y`, `env(safe-area-inset-top)` on hamburger and `main`, `env(safe-area-inset-bottom)` on chat scroll buffer |
| Sticky headers | `padding-left: 3.5rem` on all 9 page headers so titles clear the hamburger |
| Welcome | Kill desktop 700px `min-width` on `.input-container` |
| Forms | `font-size: 16px !important` on every input/select/textarea selector (iOS auto-zoom kill) |
| Touch targets | 44px min on cron, calendar, job action, dropdown, subnav, auth buttons |
| Nutrition | Column-stacked pantry form, single-column profile grid, full-width plan buttons |
| Dashboard | ECG image max-width, demographics column-stack |
| Family/Community | Wrap on member rows, `overflow-wrap: anywhere` on email, column-stacked post-form |
| Calendar | 44x44 nav buttons, flex month label |
| PDF Forms | Container padding, column button group |
| Live Video | `min-height: 100dvh`, side-pane max-height, controls stack |
| Auth | `100dvh`, safe-area top, 44px buttons |
| Chat | Long-word wrap on messages; `pre code` retains `white-space: pre` so code blocks stay block-formatted while inline code wraps |
| 360px block | Smaller welcome/header type, tighter cal grid, hide `.ss-item-desc` |

## Technical Decisions
- **One additive insert + separate 360px block**: keeps the diff reviewable and the cascade predictable. Editing earlier rules in-place would have risked regressions across desktop and the first mobile pass.
- **`font-size: 16px !important` on inputs**: iOS Safari auto-zooms when a focused input is `< 16px`, which then breaks the viewport. `!important` is needed because per-component styles already set smaller sizes with high specificity.
- **Source-order cascade over higher specificity**: appending at the end of the same media block means a single-class selector beats earlier same-class selectors, so we avoid selector arms races.
- **`padding-left: 3.5rem` on every sticky header**: the mobile hamburger sits at `top: 10px; left: 10px` and is ~40px wide, so 3.5rem reserves enough space for the title to never collide with it on any page.
- **`env(safe-area-inset-top)` and `100dvh`**: notch and home-indicator clearance on iPhone, plus `dvh` (dynamic viewport) so chrome show/hide does not clip the auth and live-video pages.

## Usage / Verification
```bash
# Serve and test on a real device or emulator
python app.py
# Open http://<lan-ip>:5000 from iPhone Safari / Android Chrome
# Toggle DevTools device toolbar -> iPhone SE, iPhone 14 Pro, Pixel 7
# Verify: hamburger never overlaps title, no zoom on input focus,
# no horizontal scroll, code blocks still scroll, buttons >= 44px
```

## Testing
8 spec checks all passed: brace balance (1314/1314), `@media (max-width: 768px)` marker present, `@media (max-width: 360px)` marker present, 10 spot-check selectors found, tinycss2 (skipped — not installed), Jinja templates parse, pytest failure count unchanged at 62 pre-existing (none CSS-related), Flask test client confirms `GET /static/style.css` returns 200 with all marker strings present. Reviewer approved Round 1.

## Known Limitations
- Tablet 769–1200px range still has the pre-existing behavior (intentionally preserved, out of scope for this pass).
- Live Video page rules target a feature that is not yet committed (`templates/tools_live_video.html` lives in the working tree only).
- The overall mobile drawer pattern is unchanged from the first pass — no animation refinements, no gesture handling.

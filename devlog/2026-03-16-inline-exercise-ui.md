# Inline Exercise Images & Calendar Widget + Today's Workout UI Fix

**Date**: 2026-03-16  |  **Status**: Completed

## What Was Built

Replaced the exercise image side-panel-only approach with inline image strips rendered directly below chat messages, added an inline mini workout widget that appears when the assistant discusses workout plans, and fixed the calendar's "Show details" button from being an oversized full-width text link to a compact pill-style button with chevron icon.

## Architecture

- **Inline image strip**: Horizontal scrollable row of 80x80 thumbnails embedded in the chat bubble. "Open full view" link still opens the existing side panel.
- **Inline workout widget**: When the assistant's response mentions a workout plan (keyword-detected), fetches today's schedule from `/api/workout-plan` and renders a compact card with exercise list, linking to the full calendar page.
- **Details button fix**: Changed from bare text button to pill with chevron SVG icon, `align-self: flex-start` to prevent stretching.

## Key Files

| File | Purpose |
|------|---------|
| `static/script.js` | Inline strip rendering in `appendMsg()`, `maybeAttachWorkoutWidget()` function |
| `static/calendar.js` | Compact details button with chevron toggle |
| `static/style.css` | `.inline-exercise-strip`, `.inline-workout-widget`, updated `.details-btn` |

## Technical Decisions

- Kept the side panel as "full view" rather than removing it — the inline strip is a preview, the panel is the detailed view.
- Workout widget detection uses simple regex on assistant text rather than a separate API flag — avoids backend changes and works retroactively on history reload.
- Chevron SVGs are inline rather than icon font — zero dependencies, tiny footprint.

## Testing

All 177 existing tests pass. JS syntax validated with `node -c`. Visual testing required in browser for layout verification.

## Known Limitations

- Workout widget keyword detection is regex-based — may miss creative phrasings or false-trigger on casual mentions of "workout plan."
- Inline strip doesn't pre-load images — relies on lazy loading, so images appear as user scrolls.

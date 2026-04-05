# Calendar Week-by-Week View & Exercise Delete

**Date**: 2026-03-16  |  **Status**: Completed

## What Was Built

Redesigned the workout calendar from a static repeating-schedule view to a **week-by-week navigable view** that shows concrete dates with past completion/missed state. Added **one-click delete buttons** on every exercise card in the calendar panel. Clicking a day in the month grid selects it and shows that week's breakdown below.

## Architecture

- **Week strip**: New UI component between month grid and day panel. Shows 7 days of the selected week with completion indicators, missed-day styling, and prev/next week navigation.
- **Day selection**: Clicking any cell in the month grid or week strip selects that day, showing its exercises in the panel below. Replaces the old "today only" panel.
- **Exercise deletion**: New `DELETE /api/workout-plan/exercise` endpoint removes a single exercise from a day. If the day becomes empty, it's removed from the schedule entirely.

## Key Files

| File | Purpose |
|------|---------|
| `functions/workout_plans.py` | New `remove_exercise()` function + `DELETE` API route |
| `static/calendar.js` | Complete rewrite: week strip, day selection, delete buttons |
| `templates/calendar.html` | Added week strip HTML structure |
| `static/style.css` | Week strip, selected cell, delete button, missed-day styles |

## Technical Decisions

- **Week offset model**: Week navigation uses offset from the selected date's week rather than absolute dates — simpler state management and anchors to the user's selection.
- **Case-insensitive delete**: Exercise name matching is case-insensitive to avoid mismatches between LLM-generated names and UI display.
- **Empty day cleanup**: When the last exercise is deleted from a day, the entire day is removed from the schedule rather than leaving an empty day — cleaner data model.
- **Optimistic UI on delete**: Card fades immediately while API call runs; reverts on failure.

## Testing

- `remove_exercise()` verified with 4 test cases: remove existing, remove last (day cleanup), non-existent day, case-insensitive match.
- All 45 physical exam tests pass.
- JS syntax validated with `node -c`.

## Known Limitations

- Week strip always shows Mon-Sun; doesn't adapt to locale-specific week starts.
- No undo for exercise deletion — could add a toast with undo but deferred.
- Past weeks show "missed" styling but don't distinguish between "rest day" and "skipped workout day" for days not in the schedule.

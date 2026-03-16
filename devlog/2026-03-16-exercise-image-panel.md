# Exercise Image Display Panel
**Date**: 2026-03-16  |  **Status**: Completed

## What Was Built
Decoupled exercise motion images from the LLM text response. Instead of embedding images inline in markdown, the system returns structured image metadata (`name` + `url`) alongside the reply. The web UI renders a "View exercise images" button that opens a slide-in panel; WhatsApp sends each image as a separate media message after the text reply.

## Architecture
The LLM response object carries an `exercise_images` list (via `resp.exercise_images`). Flask extracts it with `getattr` fallback and threads it through `handle_message` as a 3-tuple `(reply, session_id, exercise_images)`. The API endpoint conditionally includes the array in JSON only when non-empty. The TypeScript bridge deserializes it, fetches each image buffer from Flask, and sends them as native WhatsApp image messages. The web frontend receives the same array and renders a panel on demand.

## Key Files
| File | Purpose |
|------|---------|
| `whatsapp/flask_whatsapp.py` | Returns 3-tuple from `handle_message`; API conditionally includes `exercise_images` |
| `whatsapp/src/bridge.ts` | `sendWhatsAppMessage` returns `exerciseImages`; `fetchExerciseImage` downloads buffer |
| `whatsapp/src/whatsapp.ts` | `sendImage` method sends `Buffer` as WhatsApp image message via Baileys |
| `whatsapp/src/index.ts` | Loops over `exerciseImages` (capped at 5), fetches and sends each after text reply |
| `static/script.js` | `showExercisePanel` / `hideExercisePanel`; "View exercise images" button in assistant bubbles |
| `static/style.css` | Slide-in panel (right side on desktop, bottom sheet on mobile via `@media max-width: 768px`) |
| `templates/chat.html` | `#exerciseImagePanel` container with header, close button, and grid |
| `tests/test_exercise_images.py` | 12 tests covering 3-tuple return, API response, storage, error paths |

## Technical Decisions
- **Structured metadata over inline markdown**: Lets each client render images natively (WhatsApp media messages, DOM panel) rather than parsing markdown image tags.
- **Cap at 5 images on WhatsApp**: Prevents message flooding; WhatsApp rate-limits media sends.
- **Conditional JSON field**: `exercise_images` is omitted from the API response when empty to keep payloads lean.
- **Race condition guard**: `_in_flight` set prevents duplicate concurrent processing per sender; returns empty 3-tuple when blocked.
- **`img.onerror` cleanup**: If an exercise image fails to load in the panel, the card is removed entirely rather than showing a broken image.

## Usage
- **Web**: When the assistant reply includes exercises, a button appears below the message. Clicking it slides open the image panel on the right (desktop) or bottom (mobile). Close via the X button.
- **WhatsApp**: Images arrive as separate messages with the exercise name as caption, immediately after the text reply.

## Testing
177 tests passed (12 new + 165 existing). TypeScript compiles clean. New tests cover: 3-tuple return shape, exercise images present/absent, in-flight guard, missing session fallback, exception path, API response inclusion/omission, 401 auth, multi-image response, and conversation storage with/without images.

## Known Limitations
- Image cap of 5 is hardcoded in `index.ts`; not configurable.
- Panel does not persist across page navigation; reopening chat reloads images from conversation history.
- No retry logic for failed WhatsApp image sends; failures are logged and skipped.

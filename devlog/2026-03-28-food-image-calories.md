# Food Image Calorie Estimation
**Date**: 2026-03-28  |  **Status**: Completed

## What Was Built
WhatsApp users can send a photo of their meal and receive a per-item calorie and macronutrient breakdown (protein, carbs, fat, fiber), a meal total, daily budget comparison against their nutrition profile, and actionable suggestions. The feature uses gpt-4o-mini vision and is integrated as a context skill in the existing skill runtime, so it activates automatically when an image is present -- no special command needed.

## Architecture
The WhatsApp bridge already forwards image data URIs on user messages. `Agent.openai_reply` extracts images from the latest user message and passes them in `runtime_context["images"]` to the skill runtime. The `food_image_analysis` skill gates on image presence (not keyword matching), calls the vision API, parses the structured JSON response, optionally loads the user's nutrition profile for daily target comparison, and returns formatted markdown injected into the LLM context window.

## Key Files
| File | Purpose |
|------|---------|
| `functions/food_image_analyzer.py` | Core module: vision API call, JSON parsing, meal totals, profile comparison, suggestion engine, markdown formatter |
| `skills/food_image_analysis.md` | Skill definition with frontmatter (`kind: context`, `enabled_by_default: true`) and routing keywords |
| `functions/skills_runtime.py` | Executor registration (`_run_food_image_analysis`), image-presence gate in `_should_run` |
| `functions/agent.py` | Extracts `latest_user_images` from messages, passes to skill runtime, wires `food_image_summary` into LLM context |
| `tests/test_food_image.py` | 69 tests across 14 test classes |

## Technical Decisions
- **Image-presence gate, not keyword gate**: `_should_run` checks `runtime_context["images"]` instead of query keywords. A photo with no caption still triggers analysis. This was a review fix -- the original implementation required food-related text.
- **MIME validation before API call**: Only jpeg, png, gif, webp are accepted. Unsupported types (bmp, svg) return a user-friendly error without hitting the vision API.
- **Error message sanitization**: Both `JSONDecodeError` and generic exceptions return `"Unable to analyze the food image. Please try again."` -- raw exception details are never leaked to the user. This was a review fix.
- **Single-image analysis**: Only the first image in a multi-image message is analyzed, keeping API cost predictable.
- **Profile comparison is optional**: If the user has no nutrition profile, the feature still works -- it just skips the daily budget section and uses generic suggestions.

## Usage
```
# WhatsApp: send a food photo (with or without caption)
# The agent responds with item breakdown, meal total, and suggestions

# Run tests
pytest tests/test_food_image.py -v
```

## Testing
69 tests across 14 classes. All vision API calls are mocked. Coverage includes: core analysis happy path, non-food images, MIME validation (jpeg/png/gif/webp/bmp/svg), JSON code-fence stripping, malformed JSON handling, item sanitization with missing fields, float rounding, profile comparison math (including zero/negative targets), all suggestion triggers (low fiber, high calorie, low protein, high fat, low confidence), formatter output structure, skill runtime gate (images present/absent/empty/null context), executor wiring, and agent-level image extraction for both captioned and caption-less messages.

## Known Limitations
- Only the first image per message is analyzed; multi-photo meals require separate sends.
- Calorie estimates depend on gpt-4o-mini's visual portion estimation, which can vary significantly for dense or layered foods.
- No meal history accumulation -- each analysis is independent, so "remaining calories" reflects only the current meal against the daily target, not cumulative intake.
- `temperature=0.3` balances consistency vs. flexibility but means identical photos may still produce slightly different estimates across calls.

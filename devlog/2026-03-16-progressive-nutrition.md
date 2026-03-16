# Progressive Nutrition Profiling

**Date**: 2026-03-16  |  **Status**: Completed

## What Was Built

Replaced the form-first nutrition onboarding with zero-friction progressive profiling. The LLM now extracts nutrition-relevant facts (weight, allergies, diet style, goals) from natural chat via the `extract_insights` tool action and silently saves them to the user profile. The profile page shows "What I Know About You" cards grouped by category instead of empty forms. A completeness ring visualizes progress. Meal plan generation works immediately without requiring any profile setup.

## Architecture

Chat messages flow through the existing `manage_nutrition` tool. A new `extract_insights` action accepts a JSON object of extracted fields plus `_snippets` (source quotes). `merge_extracted_insights()` validates, coerces types, deduplicates list fields (allergies, preferences, goals), and writes `insight_meta` per field tracking source and timestamp. The completeness score is a weighted sum across 10 profile dimensions. The UI fetches `/api/nutrition-profile/completeness` and renders an SVG ring plus hint chips for missing fields.

## Key Files

| File | Purpose |
|------|---------|
| `functions/nutrition_plans.py` | `merge_extracted_insights()`, `compute_profile_completeness()`, `extract_insights` action, `/completeness` endpoint, removed profile gates on plan creation |
| `functions/agent.py` | `NUTRITION_TOOL` definition with `extract_insights` enum and LLM prompt for passive extraction |
| `skills/nutrition_guidance.md` | Progressive profiling instructions: be helpful first, extract facts passively, ask one follow-up at a time |
| `templates/nutrition.html` | Card-based profile view with SVG completeness ring and hidden edit form |
| `static/nutrition.js` | `renderProfileCards()`, `loadCompleteness()`, `deleteProfileField()`, chip rendering with chat-source badges |
| `tests/test_progressive_nutrition.py` | 33 tests across 5 test classes |

## Technical Decisions

- **Weighted completeness scoring** (not uniform) -- goals and preferences weigh 15 pts each since they most impact plan quality; budget is only 5 pts.
- **Insight metadata** tracks `source`, `extracted_at`, and `snippet` per field so the UI can badge chat-learned values and users can audit what was inferred.
- **List fields deduplicate while preserving order** using `dict.fromkeys()` -- repeated extractions of "vegetarian" won't stack.
- **No profile gate on plan creation** -- `generate_nutrition_plan()` handles `profile=None` gracefully, producing generic plans that improve as the profile fills in.

## Usage

User says "I'm 80 kg and allergic to shellfish" in chat. The LLM calls `manage_nutrition` with `action=extract_insights` and `details={"weight_kg":80,"allergies":["shellfish"],"_snippets":{...}}`. Profile updates silently. The profile page shows weight and allergy cards with a chat badge. Completeness ring advances.

## Testing

33 tests in `tests/test_progressive_nutrition.py` covering: `merge_extracted_insights` (14 tests -- scalars, lists, lab values, deduplication, unknown fields, meta writing), `compute_profile_completeness` (8 tests -- empty/full/partial, meta-aware scoring), `handle_nutrition_tool` extract_insights dispatch (5 tests), completeness endpoint (3 tests), profile gate removal (3 tests). All use temp directories for isolation.

## Known Limitations

- Extraction depends on the LLM correctly parsing units (e.g., "180 lbs" needs conversion to kg -- not handled server-side).
- No conflict resolution when chat-extracted values contradict earlier data; last write wins.
- Completeness ring does not account for lab value granularity (one lab filled = full 15 pts).

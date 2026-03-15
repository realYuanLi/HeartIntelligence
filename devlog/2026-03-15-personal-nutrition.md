# Personal Nutrition Skill
**Date**: 2026-03-15  |  **Status**: Completed

## What Was Built
An AI-powered nutrition skill that generates personalized 7-day meal plans, grocery lists, and nutrient-gap alerts. It uses a user profile (biometrics, allergies, dietary preferences, lab values) to compute daily macro targets via the Mifflin-St Jeor equation and cross-references lab results against RDA thresholds. Users interact through a dedicated UI or conversationally via the chat agent.

## Architecture
The skill follows a three-layer design: a **data layer** (`nutrition_search.py`) handles food database search, daily target computation, and nutrient gap detection; a **plan layer** (`nutrition_plans.py`) owns CRUD persistence, LLM-driven plan generation/modification via GPT-4o-mini, allergen validation with automatic retry, and a Flask Blueprint exposing REST endpoints; a **skill descriptor** (`nutrition_guidance.md`) integrates with the agent router, gating activation behind a GPT-4o intent classifier (`needs_nutrition_data`). The frontend (`nutrition.js` + `nutrition.html`) provides a tabbed UI for profile, meal plan, pantry, grocery, and nutrient checks. User data persists as JSON files under `personal_data/`.

## Key Files
| File | Purpose |
|---|---|
| `functions/nutrition_search.py` | Food search, Mifflin-St Jeor targets, RDA gap detection |
| `functions/nutrition_plans.py` | Plan CRUD, LLM generation, allergen validation, Flask routes |
| `skills/nutrition_guidance.md` | Skill descriptor for agent routing and context injection |
| `templates/nutrition.html` | Tabbed UI (profile, plan, pantry, grocery, nutrients) |
| `static/nutrition.js` | Client-side logic for all nutrition tabs |
| `resources/nutrition/food_nutrients.json` | Local food nutrient database |
| `resources/nutrition/rda_reference.json` | RDA reference values by age/sex |

## Technical Decisions
- **Post-generation allergen validation**: Plans are scanned for allergen matches after LLM output; a failed check triggers one retry with a stronger safety prompt at lower temperature (0.4). Residual violations surface as prominent alerts rather than silently passing.
- **Mifflin-St Jeor over Harris-Benedict**: More accurate for modern populations; goal-based adjustments (e.g., -500 kcal for weight loss) applied after TDEE calculation with a 1200-4000 kcal clamp.
- **Type validation on profile input**: All numeric fields are coerced and clamped server-side (`_validate_profile_fields`) to prevent injection of invalid data types.
- **Keyword food search with category synonyms**: Avoids external API dependency; uses token overlap scoring with minimal stemming and synonym expansion for category matching.

## Usage
```bash
# Start the app (nutrition routes auto-register via Blueprint)
python app.py

# Navigate to /nutrition in the browser for the dedicated UI
# Or ask in chat: "Create a high-protein meal plan for weight loss"
```

## Testing
```bash
pytest tests/ -q  # 120 tests, 0.42s
```
Covers: daily target computation, allergen detection/retry logic, profile field validation and type coercion, food search scoring, nutrient gap detection, plan CRUD operations, and Flask route responses.

## Known Limitations
- Food database is static JSON; no live USDA/external API integration, so nutrient data may be incomplete for uncommon foods.
- Allergen detection is substring-based (e.g., "peanut" in ingredient name); it will miss hidden allergens like "arachis oil" or cross-contamination risks.
- Plan generation depends on GPT-4o-mini output conforming to a JSON schema; malformed responses cause a user-visible error rather than graceful degradation.
- Nutrient gap analysis requires manually entered lab values; no EHR or lab provider integration exists.

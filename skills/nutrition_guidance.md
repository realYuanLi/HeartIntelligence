---
id: nutrition_guidance
title: Nutrition Guidance
executor: nutrition_guidance
kind: context
enabled_by_default: true
description: Personalized meal plans, grocery lists, recipe suggestions, and nutrient-gap alerts based on user profile, pantry, and lab values.
---

# Nutrition Guidance Skill

Use this skill to provide personalized nutrition advice including meal plans,
grocery lists, recipe ideas, and nutrient-gap analysis from a local food
database and user profile data.

Essential guidance:
- Run for context handling.
- First call `functions.nutrition_search.needs_nutrition_data(query)`.
- If nutrition data is not needed, return `activated=false`.
- If nutrition data is needed, call `functions.nutrition_search.search_foods(query)`
  and `functions.nutrition_search.format_food_results(...)`.
- Required input: `query`.
- Return `activated=true` with `nutrition_summary`.

Routing keywords: nutrition diet meal plan food recipe calorie protein carb fat
fiber vitamin mineral supplement grocery list pantry ingredient cook eat healthy
eating weight loss gain muscle bulk cut macro micronutrient nutrient gap
deficiency allergy intolerance vegan vegetarian keto paleo mediterranean
gluten-free dairy-free low-carb high-protein breakfast lunch dinner snack
prep budget cholesterol iron vitamin-d b12 calcium sodium potassium

## Progressive Profiling Behavior

1. **Always be helpful first.** Provide useful nutrition advice even when the user has zero profile data. General guidance is better than no guidance.
2. **Skip personalized calorie targets when weight/height are unknown.** Instead offer general ranges or qualitative advice (e.g. "aim for a moderate calorie deficit" rather than a specific number).
3. **Note unknown allergies gently.** When generating meal suggestions without allergy data, add a brief note like "Let me know if you have any food allergies so I can tailor recommendations."
4. **Occasionally ask ONE contextual follow-up** to fill missing profile fields — but not every message. If the user mentions food preferences, that is a natural moment to ask about goals or allergies.
5. **Extract facts from conversation.** When the user mentions personal nutrition facts in passing (e.g. "I weigh 80 kg", "I'm vegetarian", "I'm allergic to shellfish"), call `manage_nutrition` with action `extract_insights` and a JSON object of the extracted fields plus `_snippets` mapping each field to the user's exact quote.

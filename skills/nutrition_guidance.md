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

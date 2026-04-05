---
id: food_image_analysis
title: Food Image Analysis
executor: food_image_analysis
kind: context
enabled_by_default: true
description: Estimate calories and macronutrients from a photo of food, with personalized daily budget comparison.
---

# Food Image Analysis Skill

Activate this skill when the user sends a photo that may contain food and wants
nutritional information about it.

Routing keywords: food photo image picture calorie meal plate dish snack analyze
nutrition eat ate snap pic breakfast lunch dinner calories macros what did I eat
how many calories portion size

## When to activate

- The user sends an image alongside a message about food, calories, or nutrition.
- The user sends an image and asks "what is this?" or "how many calories?" or similar.
- The user sends a food photo with no text (the image itself is the query).

## How it works

1. Check `runtime_context["images"]` for attached images.
2. If images are present, call `functions.food_image_analyzer.analyze_food_image`
   with the first image data URI and the username.
3. Format the result with `functions.food_image_analyzer.format_food_image_analysis`.
4. Return `activated=true` with `food_image_summary` containing the formatted output.

## Response guidelines

- **Keep it casual and friendly.** "Looks like a pretty balanced meal!" not "Macronutrient analysis indicates adequate distribution."
- Lead with a quick overall impression ("That's around 500 calories — not bad!") before any breakdown.
- Only show the item-by-item list if the meal has 3+ items or the user asks for details. For simple meals, just give the total.
- Round numbers for readability — "about 400 calories" not "387 calories."
- If a profile comparison is available, keep it conversational: "That's about a third of your daily budget" not "33.2% of your 1,800 kcal target."
- Suggestions should feel like a friend's tip: "Next time maybe add a side salad to round it out?" not "Consider supplementing with fiber-rich vegetables."
- When estimates are uncertain, be upfront but casual: "Hard to tell the exact portion from the photo, but I'd guess around 300-400 calories."
- **Cite your method briefly.** Mention that estimates are "based on USDA nutrition data" or "cross-referenced with USDA FoodData Central." This helps users trust the numbers aren't guesses.

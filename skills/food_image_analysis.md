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

- Present the item-by-item breakdown clearly.
- Highlight the meal total prominently.
- If a profile comparison is available, contextualize remaining daily budget.
- Relay suggestions naturally as helpful tips, not commands.
- Acknowledge confidence levels: mention when estimates are uncertain.

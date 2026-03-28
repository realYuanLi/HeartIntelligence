"""Food image calorie estimation via GPT-4o vision + USDA FoodData Central cross-validation."""

import json
import logging
import os
import re

import openai
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPPORTED_MIMETYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# USDA FoodData Central API (free, public domain, 1000 req/hr)
USDA_API_BASE = "https://api.nal.usda.gov/fdc/v1"
USDA_API_KEY = os.getenv("USDA_API_KEY", "DEMO_KEY")

# USDA nutrient IDs used in search responses
_NUTRIENT_IDS = {
    "calories": 1008,   # Energy (kcal)
    "protein_g": 1003,  # Protein (g)
    "fat_g": 1004,      # Total lipid / fat (g)
    "carbs_g": 1005,    # Carbohydrate (g)
    "fiber_g": 1079,    # Fiber, total dietary (g)
}

_VISION_PROMPT = """\
You are a food nutrition analyst. Analyze the provided image and return a JSON object.

If the image does NOT contain food, return exactly:
{"detected": false, "items": []}

If the image DOES contain food, return a JSON object with this structure:
{
  "detected": true,
  "items": [
    {
      "name": "<food item name in simple English, suitable for USDA database search>",
      "estimated_portion": "<portion description, e.g. '1 cup', '200g', '1 medium slice'>",
      "portion_grams": <estimated weight in grams as a number>,
      "calories": <your estimated kcal for this portion, used as fallback>,
      "protein_g": <your estimated protein in grams>,
      "carbs_g": <your estimated carbs in grams>,
      "fat_g": <your estimated fat in grams>,
      "fiber_g": <your estimated fiber in grams>,
      "confidence": "<high|medium|low>"
    }
  ]
}

Guidelines:
- Identify every distinct food item visible in the image.
- Use common food names that would match USDA FoodData Central entries (e.g. "chicken breast cooked" not "poultry").
- Estimate portions using visual cues: plate size (~10 inch dinner plate), utensils for scale, food thickness and spread.
- Use the plate method: a standard dinner plate holds roughly 400-600g of food total.
- portion_grams should be your best estimate of the weight of that item in grams.
- For calorie and macro estimates, reference USDA standard values and scale to your estimated portion.
- Set confidence to "high" for clearly identifiable items, "medium" for partially visible, "low" for hard to distinguish.
- Return ONLY valid JSON with no additional text, markdown fences, or commentary.
"""


def _extract_mimetype(data_uri: str) -> str | None:
    """Extract MIME type from a data URI, e.g. 'data:image/jpeg;base64,...'."""
    match = re.match(r"data:(image/[a-z+]+);", data_uri)
    if match:
        return match.group(1)
    return None


def _usda_search(food_name: str) -> dict | None:
    """Search USDA FoodData Central for a food item and return per-100g nutrients.

    Returns dict with calories, protein_g, carbs_g, fat_g, fiber_g per 100g,
    or None if not found / API error.
    """
    try:
        resp = requests.post(
            f"{USDA_API_BASE}/foods/search",
            params={"api_key": USDA_API_KEY},
            json={
                "query": food_name,
                "dataType": ["Foundation", "SR Legacy"],
                "pageSize": 3,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            logger.warning("USDA API returned status %d for query '%s'", resp.status_code, food_name)
            return None

        data = resp.json()
        foods = data.get("foods", [])
        if not foods:
            return None

        # Use the first (best-match) result
        food = foods[0]
        nutrients = {}
        for fn in food.get("foodNutrients", []):
            nid = fn.get("nutrientId")
            for key, target_id in _NUTRIENT_IDS.items():
                if nid == target_id:
                    nutrients[key] = fn.get("value", 0)

        if not nutrients.get("calories"):
            return None

        return {
            "food_description": food.get("description", food_name),
            "calories_per_100g": nutrients.get("calories", 0),
            "protein_per_100g": nutrients.get("protein_g", 0),
            "carbs_per_100g": nutrients.get("carbs_g", 0),
            "fat_per_100g": nutrients.get("fat_g", 0),
            "fiber_per_100g": nutrients.get("fiber_g", 0),
            "source": "USDA FoodData Central",
        }

    except requests.RequestException as exc:
        logger.warning("USDA API request failed for '%s': %s", food_name, exc)
        return None
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("USDA API response parse error for '%s': %s", food_name, exc)
        return None


def _scale_nutrients(usda: dict, portion_grams: float) -> dict:
    """Scale per-100g USDA nutrients to actual portion size."""
    factor = portion_grams / 100.0
    return {
        "calories": round(usda["calories_per_100g"] * factor),
        "protein_g": round(usda["protein_per_100g"] * factor, 1),
        "carbs_g": round(usda["carbs_per_100g"] * factor, 1),
        "fat_g": round(usda["fat_per_100g"] * factor, 1),
        "fiber_g": round(usda["fiber_per_100g"] * factor, 1),
    }


def _compute_meal_total(items: list[dict]) -> dict:
    """Sum macronutrients across all detected food items."""
    total = {
        "calories": 0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
    }
    for item in items:
        total["calories"] += int(item.get("calories", 0))
        total["protein_g"] += float(item.get("protein_g", 0))
        total["carbs_g"] += float(item.get("carbs_g", 0))
        total["fat_g"] += float(item.get("fat_g", 0))
        total["fiber_g"] += float(item.get("fiber_g", 0))
    total["protein_g"] = round(total["protein_g"], 1)
    total["carbs_g"] = round(total["carbs_g"], 1)
    total["fat_g"] = round(total["fat_g"], 1)
    total["fiber_g"] = round(total["fiber_g"], 1)
    return total


def _compute_profile_comparison(meal_total: dict, profile: dict) -> dict:
    """Compare meal totals against user's daily nutrition targets."""
    from .nutrition_search import compute_daily_targets

    targets = compute_daily_targets(profile)
    daily_calories = targets["calories"]
    remaining = max(0, daily_calories - meal_total["calories"])

    def _pct(meal_val: float, target_val: float) -> float:
        if target_val <= 0:
            return 0.0
        return round(meal_val / target_val * 100, 1)

    return {
        "daily_target_calories": daily_calories,
        "remaining_calories": remaining,
        "protein_pct_of_target": _pct(meal_total["protein_g"], targets["protein_g"]),
        "carbs_pct_of_target": _pct(meal_total["carbs_g"], targets["carbs_g"]),
        "fat_pct_of_target": _pct(meal_total["fat_g"], targets["fat_g"]),
    }


def _generate_suggestions(meal_total: dict, profile_comparison: dict | None, items: list[dict]) -> list[str]:
    """Generate actionable nutrition suggestions based on the analysis."""
    suggestions: list[str] = []

    if not items:
        return suggestions

    # Check for low-fiber meals
    if meal_total["fiber_g"] < 3:
        suggestions.append("This meal is low in fiber. Consider adding vegetables, legumes, or whole grains.")

    # Check for high-calorie meals
    if profile_comparison:
        meal_pct = meal_total["calories"] / max(1, profile_comparison["daily_target_calories"]) * 100
        if meal_pct > 50:
            suggestions.append(
                f"This meal accounts for {meal_pct:.0f}% of your daily calorie target. "
                "Consider lighter options for your remaining meals."
            )
        if profile_comparison["protein_pct_of_target"] < 15 and meal_total["calories"] > 300:
            suggestions.append(
                "This meal is relatively low in protein. Consider adding lean protein sources "
                "like chicken, fish, eggs, or legumes."
            )
        if profile_comparison["fat_pct_of_target"] > 50:
            suggestions.append(
                "This meal is high in fat relative to your daily target. Balance with lower-fat meals later."
            )
    else:
        # Generic suggestions without profile
        if meal_total["protein_g"] < 10 and meal_total["calories"] > 300:
            suggestions.append("Consider adding a protein source to make this meal more balanced.")

    # Check confidence levels
    low_confidence = [item["name"] for item in items if item.get("confidence") == "low"]
    if low_confidence:
        names = ", ".join(low_confidence)
        suggestions.append(
            f"Some items were hard to identify ({names}). Actual nutrition values may differ."
        )

    return suggestions


def analyze_food_image(image_data_uri: str, username: str = "") -> dict:
    """Analyze a food image using GPT-4o vision + USDA FoodData Central cross-validation.

    Pipeline:
        1. GPT-4o vision identifies food items and estimates portion sizes.
        2. Each identified item is looked up in USDA FoodData Central for verified
           per-100g nutrient data (calories, protein, carbs, fat, fiber).
        3. USDA values are scaled to the estimated portion size.
        4. If USDA lookup fails for an item, GPT-4o's own estimate is used as fallback.
        5. Results are compared against the user's nutrition profile (if available).

    Args:
        image_data_uri: Base64-encoded data URI of the image.
        username: Optional username to load nutrition profile for comparison.

    Returns:
        FoodImageAnalysis dict with detected items, meal totals, profile comparison,
        and suggestions.  On any error returns {"detected": False, "items": [], "error": ...}.
    """
    try:
        # Validate mimetype
        mimetype = _extract_mimetype(image_data_uri)
        if not mimetype or mimetype not in SUPPORTED_MIMETYPES:
            return {
                "detected": False,
                "items": [],
                "error": f"Unsupported image type: {mimetype}. Supported: jpeg, png, gif, webp.",
            }

        # Step 1: GPT-4o vision identifies foods and estimates portions
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _VISION_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this food image and identify each food item with estimated portion sizes."},
                        {"type": "image_url", "image_url": {"url": image_data_uri}},
                    ],
                },
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        raw_text = response.choices[0].message.content or ""

        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()

        vision_result = json.loads(cleaned)

        if not isinstance(vision_result, dict):
            return {"detected": False, "items": [], "error": "Vision model returned non-object JSON."}

        detected = vision_result.get("detected", False)
        raw_items = vision_result.get("items", [])

        if not detected or not raw_items:
            return {
                "detected": False,
                "items": [],
                "meal_total": {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0},
                "profile_comparison": None,
                "suggestions": [],
            }

        # Step 2: Cross-reference each item with USDA FoodData Central
        enriched_items = []
        for item in raw_items:
            name = str(item.get("name", "Unknown"))
            portion_str = str(item.get("estimated_portion", "1 serving"))
            portion_grams = float(item.get("portion_grams", 100))
            confidence = str(item.get("confidence", "medium"))

            # Look up verified USDA data
            usda_data = _usda_search(name)

            if usda_data:
                # Scale USDA per-100g values to estimated portion
                scaled = _scale_nutrients(usda_data, portion_grams)
                enriched_items.append({
                    "name": name,
                    "estimated_portion": portion_str,
                    "calories": scaled["calories"],
                    "protein_g": scaled["protein_g"],
                    "carbs_g": scaled["carbs_g"],
                    "fat_g": scaled["fat_g"],
                    "fiber_g": scaled["fiber_g"],
                    "confidence": confidence,
                    "source": "USDA",
                    "usda_food": usda_data["food_description"],
                })
            else:
                # Fallback: ask GPT-4o for nutrient estimates
                enriched_items.append({
                    "name": name,
                    "estimated_portion": portion_str,
                    "calories": int(item.get("calories", 0)),
                    "protein_g": round(float(item.get("protein_g", 0)), 1),
                    "carbs_g": round(float(item.get("carbs_g", 0)), 1),
                    "fat_g": round(float(item.get("fat_g", 0)), 1),
                    "fiber_g": round(float(item.get("fiber_g", 0)), 1),
                    "confidence": confidence,
                    "source": "estimate",
                })

        meal_total = _compute_meal_total(enriched_items)

        # Step 3: Load profile if username provided
        profile_comparison = None
        if username:
            from .nutrition_plans import _load_profile
            profile = _load_profile(username)
            if profile:
                profile_comparison = _compute_profile_comparison(meal_total, profile)

        suggestions = _generate_suggestions(meal_total, profile_comparison, enriched_items)

        return {
            "detected": True,
            "items": enriched_items,
            "meal_total": meal_total,
            "profile_comparison": profile_comparison,
            "suggestions": suggestions,
        }

    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse vision model JSON response: %s", exc)
        return {"detected": False, "items": [], "error": "Unable to analyze the food image. Please try again."}
    except Exception as exc:
        logger.error("Food image analysis failed: %s", exc, exc_info=True)
        return {"detected": False, "items": [], "error": "Unable to analyze the food image. Please try again."}


def format_food_image_analysis(analysis: dict) -> str:
    """Render a FoodImageAnalysis dict as structured markdown for chat display."""
    if not analysis.get("detected"):
        error = analysis.get("error")
        if error:
            return f"Could not analyze the image: {error}"
        return ""

    items = analysis.get("items", [])
    meal_total = analysis.get("meal_total", {})
    profile_comparison = analysis.get("profile_comparison")
    suggestions = analysis.get("suggestions", [])

    lines: list[str] = []
    lines.append("**Food Analysis**\n")

    # Item-by-item breakdown
    for item in items:
        confidence_icon = {"high": "+", "medium": "~", "low": "?"}.get(item.get("confidence", "medium"), "~")
        source_tag = "USDA" if item.get("source") == "USDA" else "est."
        lines.append(
            f"- **{item['name']}** ({item['estimated_portion']}) [{confidence_icon}] [{source_tag}]\n"
            f"  {item['calories']} kcal | P: {item['protein_g']}g | C: {item['carbs_g']}g | F: {item['fat_g']}g | Fiber: {item['fiber_g']}g"
        )

    # Meal totals
    lines.append(
        f"\n**Meal Total:** {meal_total.get('calories', 0)} kcal | "
        f"P: {meal_total.get('protein_g', 0)}g | "
        f"C: {meal_total.get('carbs_g', 0)}g | "
        f"F: {meal_total.get('fat_g', 0)}g | "
        f"Fiber: {meal_total.get('fiber_g', 0)}g"
    )

    # Data source note
    usda_count = sum(1 for i in items if i.get("source") == "USDA")
    if usda_count > 0:
        lines.append(f"\n_Nutrition data: {usda_count}/{len(items)} items verified against USDA FoodData Central._")

    # Profile comparison
    if profile_comparison:
        lines.append(
            f"\n**Daily Budget:** {profile_comparison['remaining_calories']} kcal remaining "
            f"of {profile_comparison['daily_target_calories']} kcal target\n"
            f"Protein: {profile_comparison['protein_pct_of_target']}% | "
            f"Carbs: {profile_comparison['carbs_pct_of_target']}% | "
            f"Fat: {profile_comparison['fat_pct_of_target']}% of daily targets"
        )

    # Suggestions
    if suggestions:
        lines.append("\n**Suggestions:**")
        for suggestion in suggestions:
            lines.append(f"- {suggestion}")

    return "\n".join(lines)

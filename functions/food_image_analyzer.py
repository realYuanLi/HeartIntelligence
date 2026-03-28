"""Food image calorie estimation via vision model analysis."""

import json
import logging
import re

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPPORTED_MIMETYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_SYSTEM_PROMPT = """\
You are a food nutrition analyst. Analyze the provided image and return a JSON object.

If the image does NOT contain food, return exactly:
{"detected": false, "items": []}

If the image DOES contain food, return a JSON object with this structure:
{
  "detected": true,
  "items": [
    {
      "name": "<food item name>",
      "estimated_portion": "<portion size description, e.g. '1 cup', '200g', '1 medium slice'>",
      "calories": <integer kcal>,
      "protein_g": <float>,
      "carbs_g": <float>,
      "fat_g": <float>,
      "fiber_g": <float>,
      "confidence": "<high|medium|low>"
    }
  ]
}

Guidelines:
- Identify every distinct food item visible in the image.
- Estimate portions based on visual cues (plate size, utensils, relative proportions).
- Use USDA FoodData Central standard values as your reference for nutrient estimates.
- Set confidence to "high" for clearly identifiable items, "medium" for partially visible or ambiguous items, and "low" for items that are hard to distinguish.
- Return ONLY valid JSON with no additional text, markdown fences, or commentary.
"""


def _extract_mimetype(data_uri: str) -> str | None:
    """Extract MIME type from a data URI, e.g. 'data:image/jpeg;base64,...'."""
    match = re.match(r"data:(image/[a-z+]+);", data_uri)
    if match:
        return match.group(1)
    return None


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
    """Analyze a food image and return structured nutritional estimates.

    Args:
        image_data_uri: Base64-encoded data URI of the image (data:image/...;base64,...).
        username: Optional username to load nutrition profile for comparison.

    Returns:
        FoodImageAnalysis dict with detected items, meal totals, profile comparison, and suggestions.
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

        # Call vision model
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this food image and estimate the nutritional content."},
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
        items = vision_result.get("items", [])

        if not detected or not items:
            return {
                "detected": False,
                "items": [],
                "meal_total": {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0},
                "profile_comparison": None,
                "suggestions": [],
            }

        # Validate and sanitize items
        sanitized_items = []
        for item in items:
            sanitized_items.append({
                "name": str(item.get("name", "Unknown")),
                "estimated_portion": str(item.get("estimated_portion", "1 serving")),
                "calories": int(item.get("calories", 0)),
                "protein_g": round(float(item.get("protein_g", 0)), 1),
                "carbs_g": round(float(item.get("carbs_g", 0)), 1),
                "fat_g": round(float(item.get("fat_g", 0)), 1),
                "fiber_g": round(float(item.get("fiber_g", 0)), 1),
                "confidence": str(item.get("confidence", "medium")),
            })

        meal_total = _compute_meal_total(sanitized_items)

        # Load profile if username provided
        profile_comparison = None
        if username:
            from .nutrition_plans import _load_profile
            profile = _load_profile(username)
            if profile:
                profile_comparison = _compute_profile_comparison(meal_total, profile)

        suggestions = _generate_suggestions(meal_total, profile_comparison, sanitized_items)

        return {
            "detected": True,
            "items": sanitized_items,
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
    """Render a FoodImageAnalysis dict as structured markdown for chat display.

    Args:
        analysis: The dict returned by analyze_food_image.

    Returns:
        Formatted markdown string.
    """
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
        lines.append(
            f"- **{item['name']}** ({item['estimated_portion']}) [{confidence_icon}]\n"
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

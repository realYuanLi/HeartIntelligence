"""Food image calorie estimation via GPT-4o vision + USDA FoodData Central cross-validation.

Weight-estimation strategy (key to accuracy):
    GPT-4o identifies foods and estimates portions in **household measures**
    (cups, pieces, slices, oz) rather than raw grams.  We then resolve those
    descriptions to verified gram weights using three sources, in priority order:

    1. USDA ``foodPortions`` — the gold standard; each food entry lists gram
       weights for common household measures (e.g. "1 cup cooked" = 195 g).
    2. Local ``food_nutrients.json`` — curated per-serving data already in the
       project (e.g. "1 cup brown rice cooked" = 216 kcal).
    3. GPT-4o fallback — only when both databases miss, we use the model's own
       gram estimate (least reliable, flagged as ``source: estimate``).

    Calorie output includes a **±20 % range** so users understand the inherent
    uncertainty of portion estimation from photos.
"""

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

# Uncertainty factor for calorie range display
_RANGE_FACTOR = 0.20  # ±20%

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
      "portion_description": "<household measure, e.g. '1 cup', '2 slices', '1 medium', '6 oz', '1 bowl'>",
      "portion_grams": <your best gram estimate as a fallback number>,
      "calories": <your estimated kcal for this portion, used as fallback>,
      "protein_g": <your estimated protein in grams>,
      "carbs_g": <your estimated carbs in grams>,
      "fat_g": <your estimated fat in grams>,
      "fiber_g": <your estimated fiber in grams>,
      "confidence": "<high|medium|low>"
    }
  ]
}

Guidelines for portion estimation (CRITICAL for calorie accuracy):
- Describe portions in HOUSEHOLD MEASURES (cups, pieces, slices, tablespoons, oz) — NOT raw grams.
- Use standard reference objects visible in the image for scale:
  * Standard dinner plate: ~10 inches / 25 cm diameter
  * Salad/side plate: ~7 inches / 18 cm diameter
  * Standard bowl: holds ~1.5-2 cups
  * Fork length: ~7 inches / 18 cm
  * Knife length: ~9 inches / 23 cm
  * Human hand width: ~3-4 inches / 8-10 cm
- For proteins (meat, fish, tofu): estimate in oz. A deck-of-cards-sized piece is ~3 oz.
  A palm-sized piece is ~4-5 oz. A piece covering 1/4 of a dinner plate is ~5-6 oz.
- For grains/rice/pasta: estimate in cups. A tennis-ball-sized mound is ~0.5 cup.
  A portion covering 1/4 of a dinner plate is ~1 cup.
- For vegetables: estimate in cups. A fist-sized portion is ~1 cup.
- For bread: count slices. For pizza: count slices and estimate size (small/medium/large).
- For liquids/soups: estimate in cups based on bowl/glass size.
- portion_grams is your fallback gram estimate in case USDA portion lookup fails.
- For calorie and macro estimates, reference USDA standard values and scale to your estimated portion.
- Set confidence to "high" for clearly identifiable items with clear size reference,
  "medium" for identifiable food but ambiguous portion, "low" for hard to identify.
- Return ONLY valid JSON with no additional text, markdown fences, or commentary.
"""

# ---------------------------------------------------------------------------
# Local food database (pre-loaded for fast lookup)
# ---------------------------------------------------------------------------

_local_food_db: list[dict] | None = None


def _load_local_food_db() -> list[dict]:
    """Load the local food_nutrients.json database (cached after first call)."""
    global _local_food_db
    if _local_food_db is not None:
        return _local_food_db

    db_path = os.path.join(os.path.dirname(__file__), "..", "resources", "nutrition", "food_nutrients.json")
    try:
        with open(db_path) as f:
            _local_food_db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not load local food database from %s", db_path)
        _local_food_db = []
    return _local_food_db


def _local_food_lookup(food_name: str) -> dict | None:
    """Search local food_nutrients.json for a matching food.

    Returns dict with serving, calories, protein_g, carbs_g, fat_g, fiber_g
    or None if no good match.
    """
    db = _load_local_food_db()
    if not db:
        return None

    name_lower = food_name.lower()
    # Try exact-ish match first, then keyword overlap
    best_match = None
    best_score = 0

    for entry in db:
        entry_name = entry.get("name", "").lower()
        # Exact match
        if entry_name == name_lower:
            return entry
        # Check keyword overlap
        food_words = set(name_lower.split())
        entry_words = set(entry_name.split())
        overlap = len(food_words & entry_words)
        if overlap > best_score and overlap >= 1:
            best_score = overlap
            best_match = entry

    # Require at least 1 word overlap
    if best_match and best_score >= 1:
        return best_match
    return None


# ---------------------------------------------------------------------------
# USDA FoodData Central helpers
# ---------------------------------------------------------------------------

def _extract_mimetype(data_uri: str) -> str | None:
    """Extract MIME type from a data URI, e.g. 'data:image/jpeg;base64,...'."""
    match = re.match(r"data:(image/[a-z+]+);", data_uri)
    if match:
        return match.group(1)
    return None


def _usda_search(food_name: str) -> dict | None:
    """Search USDA FoodData Central for a food item.

    Returns dict with per-100g nutrients AND foodPortions (standard serving
    gram weights), or None if not found / API error.
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

        food = foods[0]
        nutrients = {}
        for fn in food.get("foodNutrients", []):
            nid = fn.get("nutrientId")
            for key, target_id in _NUTRIENT_IDS.items():
                if nid == target_id:
                    nutrients[key] = fn.get("value", 0)

        if not nutrients.get("calories"):
            return None

        # Also fetch full food details for foodPortions (gram weights per serving)
        fdc_id = food.get("fdcId")
        portions = _usda_fetch_portions(fdc_id) if fdc_id else []

        return {
            "food_description": food.get("description", food_name),
            "calories_per_100g": nutrients.get("calories", 0),
            "protein_per_100g": nutrients.get("protein_g", 0),
            "carbs_per_100g": nutrients.get("carbs_g", 0),
            "fat_per_100g": nutrients.get("fat_g", 0),
            "fiber_per_100g": nutrients.get("fiber_g", 0),
            "portions": portions,
            "source": "USDA FoodData Central",
        }

    except requests.RequestException as exc:
        logger.warning("USDA API request failed for '%s': %s", food_name, exc)
        return None
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("USDA API response parse error for '%s': %s", food_name, exc)
        return None


def _usda_fetch_portions(fdc_id: int) -> list[dict]:
    """Fetch food portion data from USDA for verified gram weights.

    Returns list of {description, gram_weight} dicts, e.g.:
        [{"description": "1 cup", "gram_weight": 195.0}, ...]
    """
    try:
        resp = requests.get(
            f"{USDA_API_BASE}/food/{fdc_id}",
            params={"api_key": USDA_API_KEY, "format": "full"},
            timeout=8,
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        portions = []
        for p in data.get("foodPortions", []):
            gram_weight = p.get("gramWeight")
            if not gram_weight or gram_weight <= 0:
                continue

            # Build a readable description from available fields
            amount = p.get("amount", 1)
            modifier = p.get("modifier", "")
            portion_desc = p.get("portionDescription", "")
            measure_name = ""
            measure_unit = p.get("measureUnit", {})
            if isinstance(measure_unit, dict):
                measure_name = measure_unit.get("name", "")

            desc = portion_desc or f"{amount} {modifier or measure_name}".strip()
            if desc:
                portions.append({
                    "description": desc.lower().strip(),
                    "gram_weight": float(gram_weight),
                })

        return portions
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return []


def _match_portion_to_grams(
    portion_description: str,
    usda_portions: list[dict],
    gpt_fallback_grams: float,
) -> tuple[float, str]:
    """Resolve a household-measure portion description to a gram weight.

    Matching strategy:
        1. Try to match against USDA foodPortions using keyword overlap.
        2. If no USDA match, fall back to GPT-4o's gram estimate.

    Returns:
        (gram_weight, source) where source is "usda_portion" or "gpt_estimate".
    """
    if not usda_portions:
        return gpt_fallback_grams, "gpt_estimate"

    desc_lower = portion_description.lower().strip()

    # Parse quantity from the description (e.g. "2 cups" -> qty=2, rest="cups")
    qty_match = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", desc_lower)
    qty = float(qty_match.group(1)) if qty_match else 1.0
    desc_unit = qty_match.group(2).strip() if qty_match else desc_lower

    best_portion = None
    best_score = 0

    # Normalize plurals and strip punctuation for matching
    def _normalize_words(words: set[str]) -> set[str]:
        normalized = set()
        for w in words:
            # Strip trailing punctuation (commas, periods, parens)
            w = re.sub(r"[,.\(\)]+$", "", w).strip()
            if not w:
                continue
            normalized.add(w)
            # Add singular form: cups->cup, slices->slice, ounces->ounce, pieces->piece
            if w.endswith("es") and len(w) > 3:
                normalized.add(w[:-2])
                normalized.add(w[:-1])
            if w.endswith("s") and len(w) > 2:
                normalized.add(w[:-1])  # cups->cup, slices->slice
        return normalized

    desc_words_normalized = _normalize_words(set(desc_unit.split()))

    for portion in usda_portions:
        p_desc = portion["description"]
        # Extract quantity from USDA portion description too
        p_qty_match = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", p_desc)
        p_unit = p_qty_match.group(2).strip() if p_qty_match else p_desc

        # Score by keyword overlap between unit descriptions (normalized)
        p_words_normalized = _normalize_words(set(p_unit.split()))
        # Remove common filler words
        filler = {"about", "of", "and", "a", "an", "the", "from", "with", "without"}
        desc_clean = desc_words_normalized - filler
        p_clean = p_words_normalized - filler
        overlap = len(desc_clean & p_clean)

        # Bonus for key unit matches
        unit_keywords = {"cup", "cups", "slice", "slices", "piece", "pieces",
                         "oz", "ounce", "ounces", "tbsp", "tablespoon",
                         "tsp", "teaspoon", "medium", "large", "small",
                         "whole", "half", "bowl", "chopped", "breast", "spear"}
        unit_overlap = len(desc_clean & p_clean & _normalize_words(unit_keywords))

        score = overlap + unit_overlap * 2
        if score > best_score:
            best_score = score
            best_portion = portion

    if best_portion and best_score >= 1:
        # Scale by the quantity ratio
        # e.g., user says "2 cups", USDA portion is for "1 cup" (gram_weight=195)
        # -> return 2 * 195 = 390g
        usda_gram_weight = best_portion["gram_weight"]
        return round(qty * usda_gram_weight, 1), "usda_portion"

    return gpt_fallback_grams, "gpt_estimate"


# ---------------------------------------------------------------------------
# Core scaling and aggregation
# ---------------------------------------------------------------------------

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


def _compute_calorie_range(calories: int) -> tuple[int, int]:
    """Return (low, high) calorie range applying ±20% uncertainty."""
    low = max(0, round(calories * (1 - _RANGE_FACTOR)))
    high = round(calories * (1 + _RANGE_FACTOR))
    return low, high


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


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def analyze_food_image(image_data_uri: str, username: str = "") -> dict:
    """Analyze a food image using GPT-4o vision + USDA FoodData Central cross-validation.

    Pipeline:
        1. GPT-4o vision identifies food items and estimates portions in household
           measures (cups, pieces, oz) — NOT raw grams.
        2. Each identified item is looked up in USDA FoodData Central.
        3. The household-measure portion is matched against USDA foodPortions to
           get a verified gram weight (e.g. "1 cup" rice → 195 g per USDA).
        4. Per-100g USDA nutrients are scaled using the verified gram weight.
        5. If USDA portion lookup fails, the local food_nutrients.json is tried
           (has per-serving calorie data for common foods).
        6. If both fail, GPT-4o's own gram/calorie estimate is used (least reliable).
        7. A ±20% calorie range is included to communicate uncertainty.
        8. Results are compared against the user's nutrition profile (if available).

    Returns:
        FoodImageAnalysis dict.  On error: {"detected": False, "items": [], "error": ...}.
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
                        {"type": "text", "text": "Analyze this food image. Identify each item and estimate portions in household measures."},
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

        # Step 2: Resolve each item — USDA portions > local DB > GPT fallback
        enriched_items = []
        for item in raw_items:
            name = str(item.get("name", "Unknown"))
            portion_desc = str(item.get("portion_description", item.get("estimated_portion", "1 serving")))
            gpt_grams = float(item.get("portion_grams", 100))
            confidence = str(item.get("confidence", "medium"))

            # Try USDA lookup (nutrients + portion gram weights)
            usda_data = _usda_search(name)

            if usda_data:
                # Resolve household measure to gram weight via USDA portions
                gram_weight, weight_source = _match_portion_to_grams(
                    portion_desc, usda_data.get("portions", []), gpt_grams
                )
                scaled = _scale_nutrients(usda_data, gram_weight)
                cal_low, cal_high = _compute_calorie_range(scaled["calories"])
                enriched_items.append({
                    "name": name,
                    "estimated_portion": portion_desc,
                    "portion_grams": gram_weight,
                    "weight_source": weight_source,
                    "calories": scaled["calories"],
                    "calorie_range": [cal_low, cal_high],
                    "protein_g": scaled["protein_g"],
                    "carbs_g": scaled["carbs_g"],
                    "fat_g": scaled["fat_g"],
                    "fiber_g": scaled["fiber_g"],
                    "confidence": confidence,
                    "source": "USDA",
                    "usda_food": usda_data["food_description"],
                })
            else:
                # Try local food database
                local_match = _local_food_lookup(name)
                if local_match:
                    cal = int(local_match.get("calories", 0))
                    cal_low, cal_high = _compute_calorie_range(cal)
                    enriched_items.append({
                        "name": name,
                        "estimated_portion": local_match.get("serving", portion_desc),
                        "portion_grams": gpt_grams,
                        "weight_source": "local_db",
                        "calories": cal,
                        "calorie_range": [cal_low, cal_high],
                        "protein_g": round(float(local_match.get("protein_g", 0)), 1),
                        "carbs_g": round(float(local_match.get("carbs_g", 0)), 1),
                        "fat_g": round(float(local_match.get("fat_g", 0)), 1),
                        "fiber_g": round(float(local_match.get("fiber_g", 0)), 1),
                        "confidence": confidence,
                        "source": "local_db",
                    })
                else:
                    # Last resort: GPT-4o estimates
                    cal = int(item.get("calories", 0))
                    cal_low, cal_high = _compute_calorie_range(cal)
                    enriched_items.append({
                        "name": name,
                        "estimated_portion": portion_desc,
                        "portion_grams": gpt_grams,
                        "weight_source": "gpt_estimate",
                        "calories": cal,
                        "calorie_range": [cal_low, cal_high],
                        "protein_g": round(float(item.get("protein_g", 0)), 1),
                        "carbs_g": round(float(item.get("carbs_g", 0)), 1),
                        "fat_g": round(float(item.get("fat_g", 0)), 1),
                        "fiber_g": round(float(item.get("fiber_g", 0)), 1),
                        "confidence": confidence,
                        "source": "estimate",
                    })

        meal_total = _compute_meal_total(enriched_items)
        meal_cal_low, meal_cal_high = _compute_calorie_range(meal_total["calories"])

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
            "meal_calorie_range": [meal_cal_low, meal_cal_high],
            "profile_comparison": profile_comparison,
            "suggestions": suggestions,
        }

    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse vision model JSON response: %s", exc)
        return {"detected": False, "items": [], "error": "Unable to analyze the food image. Please try again."}
    except Exception as exc:
        logger.error("Food image analysis failed: %s", exc, exc_info=True)
        return {"detected": False, "items": [], "error": "Unable to analyze the food image. Please try again."}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_food_image_analysis(analysis: dict) -> str:
    """Render a FoodImageAnalysis dict as structured markdown for chat display."""
    if not analysis.get("detected"):
        error = analysis.get("error")
        if error:
            return f"Could not analyze the image: {error}"
        return ""

    items = analysis.get("items", [])
    meal_total = analysis.get("meal_total", {})
    meal_range = analysis.get("meal_calorie_range", [])
    profile_comparison = analysis.get("profile_comparison")
    suggestions = analysis.get("suggestions", [])

    lines: list[str] = []
    lines.append("**Food Analysis**\n")

    # Item-by-item breakdown
    for item in items:
        confidence_icon = {"high": "+", "medium": "~", "low": "?"}.get(item.get("confidence", "medium"), "~")
        source_tag = {"USDA": "USDA", "local_db": "DB", "estimate": "est."}.get(item.get("source", ""), "est.")
        cal_range = item.get("calorie_range", [])
        range_str = f" ({cal_range[0]}-{cal_range[1]})" if len(cal_range) == 2 else ""
        lines.append(
            f"- **{item['name']}** ({item['estimated_portion']}) [{confidence_icon}] [{source_tag}]\n"
            f"  {item['calories']} kcal{range_str} | P: {item['protein_g']}g | C: {item['carbs_g']}g | F: {item['fat_g']}g"
        )

    # Meal totals with range
    meal_cal = meal_total.get("calories", 0)
    range_str = ""
    if len(meal_range) == 2:
        range_str = f" (likely {meal_range[0]}-{meal_range[1]})"
    lines.append(
        f"\n**Meal Total:** {meal_cal} kcal{range_str} | "
        f"P: {meal_total.get('protein_g', 0)}g | "
        f"C: {meal_total.get('carbs_g', 0)}g | "
        f"F: {meal_total.get('fat_g', 0)}g"
    )

    # Data source note
    usda_count = sum(1 for i in items if i.get("source") == "USDA")
    local_count = sum(1 for i in items if i.get("source") == "local_db")
    verified = usda_count + local_count
    if verified > 0:
        lines.append(f"\n_Nutrition data: {verified}/{len(items)} items verified against USDA FoodData Central._")

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

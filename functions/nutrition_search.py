"""Nutrition data layer: food search, daily target computation, nutrient gap detection."""

import json
import logging
import re
from pathlib import Path

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_FOODS: list[dict] | None = None
_FOOD_DB_PATH = Path(__file__).resolve().parent.parent / "resources" / "nutrition" / "food_nutrients.json"
_RDA_PATH = Path(__file__).resolve().parent.parent / "resources" / "nutrition" / "rda_reference.json"
_RDA: dict | None = None

# Words that add noise to scoring — filtered from query before matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "and", "or", "but", "not", "no", "nor", "so", "if", "then",
    "i", "me", "my", "we", "us", "you", "your", "he", "she", "it",
    "show", "give", "tell", "find", "get", "want", "need", "like",
    "what", "how", "which", "some", "good", "best", "great", "recommend",
    "food", "foods", "eat", "eating", "meal", "meals", "please", "help",
})

# Maps common user terms to database category values
_CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "meat": ["protein"],
    "fish": ["protein"],
    "seafood": ["protein"],
    "chicken": ["protein"],
    "beef": ["protein"],
    "pork": ["protein"],
    "dairy": ["dairy"],
    "milk": ["dairy"],
    "cheese": ["dairy"],
    "yogurt": ["dairy"],
    "grain": ["grains"],
    "grains": ["grains"],
    "carb": ["grains"],
    "carbs": ["grains"],
    "bread": ["grains"],
    "rice": ["grains"],
    "pasta": ["grains"],
    "vegetable": ["vegetables"],
    "vegetables": ["vegetables"],
    "veggie": ["vegetables"],
    "veggies": ["vegetables"],
    "fruit": ["fruits"],
    "fruits": ["fruits"],
    "nut": ["nuts_seeds"],
    "nuts": ["nuts_seeds"],
    "seed": ["nuts_seeds"],
    "seeds": ["nuts_seeds"],
    "legume": ["legumes"],
    "legumes": ["legumes"],
    "bean": ["legumes"],
    "beans": ["legumes"],
    "lentil": ["legumes"],
    "lentils": ["legumes"],
    "oil": ["fats_oils"],
    "fat": ["fats_oils"],
    "fats": ["fats_oils"],
    "condiment": ["condiments"],
    "sauce": ["condiments"],
    "drink": ["beverages"],
    "beverage": ["beverages"],
    "supplement": ["supplements"],
    "protein powder": ["supplements"],
}


def _load_foods() -> list[dict]:
    """Lazy-load the food nutrients database."""
    global _FOODS
    if _FOODS is not None:
        return _FOODS
    try:
        with open(_FOOD_DB_PATH, "r", encoding="utf-8") as f:
            _FOODS = json.load(f)
    except Exception as exc:
        logger.error("Failed to load food database: %s", exc)
        _FOODS = []
    return _FOODS


def _load_rda() -> dict:
    """Lazy-load RDA reference data."""
    global _RDA
    if _RDA is not None:
        return _RDA
    try:
        with open(_RDA_PATH, "r", encoding="utf-8") as f:
            _RDA = json.load(f)
    except Exception as exc:
        logger.error("Failed to load RDA reference: %s", exc)
        _RDA = {}
    return _RDA


def needs_nutrition_data(query: str) -> bool:
    """Use GPT-4o to decide if a query needs nutrition/food information."""
    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a decision maker. Determine if a user query requires nutrition, food, diet, or meal planning information to answer accurately.

Return ONLY "YES" for:
- Requests for meal plans, recipes, or food recommendations
- Questions about specific foods, nutrients, or dietary needs
- Queries mentioning calories, macros, vitamins, minerals, or supplements
- Requests for grocery lists or pantry management
- Questions about dietary preferences (vegan, keto, Mediterranean, etc.)
- Nutrient gap or deficiency discussions
- Food allergy or intolerance related queries

Return ONLY "NO" for:
- General health questions not about nutrition (exercise, medication, symptoms)
- Questions unrelated to food or diet
- Simple greetings or casual conversation
- Exercise or workout questions

Examples:
- "What should I eat for dinner?" → YES
- "Create a meal plan for weight loss" → YES
- "What foods are high in iron?" → YES
- "I need a grocery list" → YES
- "What are good chest exercises?" → NO
- "What is hypertension?" → NO
- "Hello, how are you?" → NO""",
                },
                {"role": "user", "content": f"Query: {query}"},
            ],
            temperature=0,
            max_tokens=3,
        )
        decision = response.choices[0].message.content.strip().upper()
        return decision == "YES"
    except Exception as exc:
        logger.error("Error in needs_nutrition_data: %s", exc)
        return False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _stem(token: str) -> str:
    """Minimal stemming: strip trailing 's' for plural matching."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokenize(text: str) -> list[str]:
    """Tokenize, stem, return list (preserving order)."""
    raw = re.findall(r"[a-z0-9]+", _normalize(text))
    return [_stem(t) for t in raw]


def search_foods(query: str, max_results: int = 10) -> list[dict]:
    """Search foods using keyword scoring against the food database."""
    foods = _load_foods()
    if not foods:
        return []

    normalized = _normalize(query)
    tokens = _tokenize(query)
    clean_tokens = {t for t in tokens if t not in _STOP_WORDS}

    if not clean_tokens:
        return []

    # Detect target categories
    target_categories: set[str] = set()
    raw_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    for synonym, categories in _CATEGORY_SYNONYMS.items():
        syn_tokens = set(_tokenize(synonym))
        if syn_tokens and syn_tokens.issubset(raw_tokens | clean_tokens):
            target_categories.update(categories)

    # Detect nutrient focus
    nutrient_keywords = {
        "protein": "protein_g",
        "carb": "carbs_g",
        "fat": "fat_g",
        "fiber": "fiber_g",
        "calcium": "calcium_mg",
        "iron": "iron_mg",
        "vitamin": "vitamin_d_mcg",
    }
    sort_nutrient = None
    sort_high = True
    for kw, field in nutrient_keywords.items():
        if kw in clean_tokens or kw in raw_tokens:
            sort_nutrient = field
            break
    if "low" in raw_tokens:
        sort_high = False

    scored: list[tuple[dict, float]] = []

    for food in foods:
        score = 0.0

        # Name token overlap (weight 3.0 per token)
        food_name_tokens = set(_tokenize(food.get("name", "")))
        name_overlap = clean_tokens & food_name_tokens
        score += len(name_overlap) * 3.0

        # Category match (weight 2.0)
        food_category = food.get("category", "")
        if target_categories and food_category in target_categories:
            score += 2.0

        if score > 0:
            scored.append((food, score))

    scored.sort(key=lambda item: item[1], reverse=True)

    results = [food for food, _ in scored[:max_results]]

    # If no name matches but we have a category, return top items from that category
    if not results and target_categories:
        category_foods = [f for f in foods if f.get("category") in target_categories]
        if sort_nutrient:
            category_foods.sort(
                key=lambda f: f.get(sort_nutrient, 0),
                reverse=sort_high,
            )
        results = category_foods[:max_results]

    # If we have a nutrient sort and results, re-sort by that nutrient
    if sort_nutrient and results:
        results.sort(key=lambda f: f.get(sort_nutrient, 0), reverse=sort_high)

    return results


def format_food_results(foods: list[dict]) -> str:
    """Format food results as concise structured markdown for LLM context."""
    if not foods:
        return ""

    sections = []
    for i, food in enumerate(foods, 1):
        name = food.get("name", "Unknown").title()
        serving = food.get("serving", "1 serving")
        calories = food.get("calories", 0)
        protein = food.get("protein_g", 0)
        carbs = food.get("carbs_g", 0)
        fat = food.get("fat_g", 0)
        fiber = food.get("fiber_g", 0)
        category = food.get("category", "other").replace("_", " ").title()

        section = f"### {i}. {name}\n"
        section += f"**{category} | {serving}**\n"
        section += f"Calories: {calories} | Protein: {protein}g | Carbs: {carbs}g | Fat: {fat}g | Fiber: {fiber}g\n"
        sections.append(section)

    header = f"**Food Database — {len(foods)} results:**\n\n"
    return header + "\n---\n\n".join(sections)


def _get_rda_key(profile: dict) -> str:
    """Determine the RDA lookup key from a user profile."""
    age = profile.get("age", 30)
    sex = profile.get("sex", "male").lower()
    if age <= 30:
        age_range = "19-30"
    elif age <= 50:
        age_range = "31-50"
    elif age <= 70:
        age_range = "51-70"
    else:
        age_range = "71+"
    return f"{age_range}_{sex}"


def compute_daily_targets(profile: dict) -> dict:
    """Compute daily macro targets using Mifflin-St Jeor equation.

    Returns dict with keys: calories, protein_g, carbs_g, fat_g, fiber_g.
    """
    weight_kg = profile.get("weight_kg", 70.0)
    height_cm = profile.get("height_cm", 170.0)
    age = profile.get("age", 30)
    sex = profile.get("sex", "male").lower()
    activity_level = profile.get("activity_level", "moderate").lower()
    goals = profile.get("health_goals", [])

    # Mifflin-St Jeor BMR
    if sex == "female":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5

    # Activity multiplier
    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    multiplier = activity_multipliers.get(activity_level, 1.55)
    tdee = bmr * multiplier

    # Goal adjustment
    if "weight_loss" in goals:
        tdee -= 500
    elif "weight_gain" in goals or "muscle_gain" in goals:
        tdee += 300

    # Clamp to 1200-4000
    calories = max(1200, min(4000, round(tdee)))

    # Macro split
    if "muscle_gain" in goals:
        protein_g = round(weight_kg * 2.0)
        fat_g = round(calories * 0.25 / 9)
    elif "weight_loss" in goals:
        protein_g = round(weight_kg * 1.8)
        fat_g = round(calories * 0.25 / 9)
    else:
        protein_g = round(weight_kg * 1.6)
        fat_g = round(calories * 0.30 / 9)

    # Remaining calories from carbs
    carbs_g = round((calories - protein_g * 4 - fat_g * 9) / 4)
    carbs_g = max(50, carbs_g)

    # Fiber target
    rda = _load_rda()
    rda_key = _get_rda_key(profile)
    rda_values = rda.get(rda_key, {})
    fiber_g = rda_values.get("fiber_g", 30)

    return {
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "fiber_g": fiber_g,
    }


def detect_nutrient_gaps(profile: dict, plan: dict | None = None) -> list[dict]:
    """Compare user lab values against RDA and return nutrient gap alerts.

    Each alert: {nutrient, status, message, food_suggestions}
    """
    rda = _load_rda()
    rda_key = _get_rda_key(profile)
    rda_values = rda.get(rda_key, {})
    if not rda_values:
        return []

    lab_values = profile.get("lab_values", {})
    if not lab_values:
        return []

    # Check if all lab values are null
    has_any_value = any(v is not None for v in lab_values.values())
    if not has_any_value:
        return [{
            "nutrient": "General",
            "status": "unknown",
            "message": "No lab values available. Consider getting blood work to identify potential nutrient gaps.",
            "food_suggestions": [],
        }]

    gaps = []

    # Lab-to-RDA mapping and food suggestions
    lab_checks = {
        "vitamin_d_ng_ml": {
            "rda_key": "vitamin_d_ng_ml",
            "name": "Vitamin D",
            "unit": "ng/mL",
            "low_foods": ["salmon", "trout", "mackerel", "fortified milk", "egg yolks", "sardines"],
        },
        "iron_ug_dl": {
            "rda_key": "iron_ug_dl",
            "name": "Iron",
            "unit": "ug/dL",
            "low_foods": ["spinach", "lentils", "red meat", "clams", "pumpkin seeds", "dark chocolate"],
        },
        "cholesterol_total_mg_dl": {
            "rda_key": "cholesterol_total_mg_dl",
            "name": "Total Cholesterol",
            "unit": "mg/dL",
            "high_foods": ["oats", "almonds", "olive oil", "salmon", "avocado", "beans"],
        },
        "ldl_mg_dl": {
            "rda_key": "ldl_mg_dl",
            "name": "LDL Cholesterol",
            "unit": "mg/dL",
            "high_foods": ["oats", "walnuts", "olive oil", "beans", "eggplant", "barley"],
        },
        "hdl_mg_dl": {
            "rda_key": "hdl_mg_dl",
            "name": "HDL Cholesterol",
            "unit": "mg/dL",
            "low_foods": ["salmon", "olive oil", "avocado", "nuts", "flax seeds", "dark chocolate"],
        },
        "b12_pg_ml": {
            "rda_key": "vitamin_b12_pg_ml",
            "name": "Vitamin B12",
            "unit": "pg/mL",
            "low_foods": ["sardines", "salmon", "tuna", "nutritional yeast", "eggs", "fortified milk"],
        },
        "hba1c_pct": {
            "rda_key": "hba1c_pct",
            "name": "HbA1c",
            "unit": "%",
            "high_foods": ["leafy greens", "whole grains", "legumes", "cinnamon", "berries", "nuts"],
        },
    }

    for lab_key, check in lab_checks.items():
        value = lab_values.get(lab_key)
        if value is None:
            continue

        rda_target = rda_values.get(check["rda_key"])
        if rda_target is None:
            continue

        name = check["name"]
        unit = check["unit"]

        # Determine if this is a "lower is better" or "higher is better" metric
        if lab_key in ("cholesterol_total_mg_dl", "ldl_mg_dl", "hba1c_pct"):
            # High is bad
            if value > rda_target:
                gaps.append({
                    "nutrient": name,
                    "status": "high",
                    "message": f"Your {name} is {value} {unit}, above the optimal threshold of {rda_target} {unit}.",
                    "food_suggestions": check.get("high_foods", []),
                })
        elif lab_key == "hdl_mg_dl":
            # Low HDL is bad
            if value < rda_target:
                gaps.append({
                    "nutrient": name,
                    "status": "low",
                    "message": f"Your {name} is {value} {unit}, below the optimal level of {rda_target} {unit}.",
                    "food_suggestions": check.get("low_foods", []),
                })
        else:
            # Low is bad (vitamin D, iron, B12)
            if value < rda_target:
                gaps.append({
                    "nutrient": name,
                    "status": "low",
                    "message": f"Your {name} is {value} {unit}, below the recommended level of {rda_target} {unit}.",
                    "food_suggestions": check.get("low_foods", []),
                })

    return gaps

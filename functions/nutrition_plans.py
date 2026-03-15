"""Nutrition plan persistence, CRUD API, LLM plan generation, and Flask Blueprint."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import openai
from dotenv import load_dotenv
from flask import Blueprint, jsonify, render_template, request, session

load_dotenv()

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = APP_DIR / "personal_data" / "nutrition_profiles"
PLANS_DIR = APP_DIR / "personal_data" / "nutrition_plans"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
PLANS_DIR.mkdir(parents=True, exist_ok=True)

nutrition_bp = Blueprint("nutrition", __name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _username() -> Optional[str]:
    return session.get("username")


def _require_login():
    u = session.get("username")
    return bool(u)


def _profile_path(username: str) -> Path:
    return PROFILES_DIR / f"{username}.json"


def _pantry_path(username: str) -> Path:
    return PROFILES_DIR / f"{username}_pantry.json"


def _plan_path(username: str) -> Path:
    return PLANS_DIR / f"{username}.json"


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE = {
    "age": 30,
    "weight_kg": 70.0,
    "height_cm": 170.0,
    "sex": "male",
    "activity_level": "moderate",
    "allergies": [],
    "dietary_preferences": [],
    "health_goals": [],
    "weekly_budget_usd": None,
    "lab_values": {
        "vitamin_d_ng_ml": None,
        "iron_ug_dl": None,
        "cholesterol_total_mg_dl": None,
        "ldl_mg_dl": None,
        "hdl_mg_dl": None,
        "b12_pg_ml": None,
        "hba1c_pct": None,
    },
    "updated_at": None,
}


def _load_profile(username: str) -> dict | None:
    p = _profile_path(username)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_profile(username: str, profile: dict):
    p = _profile_path(username)
    p.parent.mkdir(parents=True, exist_ok=True)
    profile["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with p.open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Pantry CRUD
# ---------------------------------------------------------------------------

def _load_pantry(username: str) -> dict:
    p = _pantry_path(username)
    if not p.exists():
        return {"items": [], "updated_at": None}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": [], "updated_at": None}


def _save_pantry(username: str, pantry: dict):
    p = _pantry_path(username)
    p.parent.mkdir(parents=True, exist_ok=True)
    pantry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with p.open("w", encoding="utf-8") as f:
        json.dump(pantry, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Plan CRUD
# ---------------------------------------------------------------------------

def _load_plans(username: str) -> list[dict]:
    p = _plan_path(username)
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return [data]
    except Exception:
        return []


def _save_plans(username: str, plans: list[dict]):
    p = _plan_path(username)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(plans, f, indent=2, ensure_ascii=False)


def _get_active_plan(username: str) -> Optional[dict]:
    plans = _load_plans(username)
    for plan in plans:
        if plan.get("active"):
            return plan
    return None


def _set_active_plan(username: str, plan: dict):
    """Save plan as active, deactivating any previous active plan."""
    plans = _load_plans(username)
    for p in plans:
        if p.get("active"):
            p["active"] = False
    plans.append(plan)
    _save_plans(username, plans)


def _update_active_plan(username: str, updated_plan: dict):
    """Replace the active plan in-place."""
    plans = _load_plans(username)
    for i, p in enumerate(plans):
        if p.get("plan_id") == updated_plan.get("plan_id"):
            plans[i] = updated_plan
            _save_plans(username, plans)
            return
    plans.append(updated_plan)
    _save_plans(username, plans)


# ---------------------------------------------------------------------------
# LLM Plan Generation
# ---------------------------------------------------------------------------

_PLAN_SCHEMA = {
    "title": "string — short descriptive title",
    "duration_days": 7,
    "daily_targets": {
        "calories": "int",
        "protein_g": "int",
        "carbs_g": "int",
        "fat_g": "int",
        "fiber_g": "int",
    },
    "days": {
        "<day_of_week>": {
            "meals": [
                {
                    "meal_type": "breakfast|lunch|dinner|snack",
                    "name": "string — meal name",
                    "ingredients": [{"name": "string", "amount": "string"}],
                    "prep_time_min": "int",
                    "calories": "int",
                    "protein_g": "float",
                    "carbs_g": "float",
                    "fat_g": "float",
                    "recipe_steps": ["string"],
                }
            ]
        }
    },
    "grocery_list": [
        {"name": "string", "amount": "string", "category": "string", "estimated_cost_usd": "float or null"}
    ],
}

_GENERATE_SYSTEM = f"""You are a nutrition plan generator. Return ONLY valid JSON matching this schema:
{json.dumps(_PLAN_SCHEMA, indent=2)}

Rules:
- days keys must be lowercase day names (monday through sunday)
- meal_type must be one of: breakfast, lunch, dinner, snack
- Include realistic calorie and macro counts for each meal
- Provide step-by-step recipe instructions in recipe_steps
- grocery_list should consolidate all ingredients across the week
- category in grocery_list should be one of: protein, dairy, grains, vegetables, fruits, nuts_seeds, legumes, fats_oils, condiments, beverages, other
- estimated_cost_usd can be null if unknown
- Return ONLY the JSON object, no markdown fences, no explanation."""


def _build_generation_prompt(
    user_request: str,
    profile: dict | None = None,
    pantry: dict | None = None,
) -> str:
    """Build a detailed prompt for meal plan generation."""
    parts = [f"User request: {user_request}"]

    if profile:
        from .nutrition_search import compute_daily_targets, detect_nutrient_gaps

        targets = compute_daily_targets(profile)
        parts.append(f"\nDaily calorie target: {targets['calories']} kcal")
        parts.append(f"Macro targets — Protein: {targets['protein_g']}g, Carbs: {targets['carbs_g']}g, Fat: {targets['fat_g']}g, Fiber: {targets['fiber_g']}g")

        allergies = profile.get("allergies", [])
        if allergies:
            parts.append(f"\nALLERGIES (MUST AVOID): {', '.join(allergies)}")

        prefs = profile.get("dietary_preferences", [])
        if prefs:
            parts.append(f"Dietary preferences: {', '.join(prefs)}")

        goals = profile.get("health_goals", [])
        if goals:
            parts.append(f"Health goals: {', '.join(goals)}")

        budget = profile.get("weekly_budget_usd")
        if budget:
            parts.append(f"Weekly grocery budget: ${budget}")

        gaps = detect_nutrient_gaps(profile)
        if gaps:
            gap_lines = [f"- {g['nutrient']}: {g['message']}" for g in gaps if g["status"] != "unknown"]
            if gap_lines:
                parts.append(f"\nNutrient gaps to address:\n" + "\n".join(gap_lines))

    if pantry and pantry.get("items"):
        pantry_names = [item["name"] for item in pantry["items"][:20]]
        parts.append(f"\nAvailable in pantry: {', '.join(pantry_names)}")
        parts.append("Try to incorporate pantry items where appropriate.")

    parts.append("\nGenerate a 7-day meal plan with the daily targets listed above. Include breakfast, lunch, dinner, and one snack per day.")
    return "\n".join(parts)


def generate_nutrition_plan(user_request: str, username: str) -> dict:
    """Use LLM to generate a nutrition plan."""
    profile = _load_profile(username)
    pantry = _load_pantry(username)
    prompt = _build_generation_prompt(user_request, profile, pantry)

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.7,
            messages=[
                {"role": "system", "content": _GENERATE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        plan_data = json.loads(raw)

        # Validate allergens if profile exists; retry once on failure
        allergen_warnings: list[dict] = []
        if profile:
            allergies = profile.get("allergies", [])
            allergen_warnings = _validate_allergens(plan_data, allergies)

            if allergen_warnings and allergies:
                # Attempt ONE regeneration with a stronger allergen-avoidance prompt
                logger.info("Allergens detected in first attempt; regenerating with stronger prompt.")
                allergen_list = ", ".join(allergies)
                retry_prompt = (
                    prompt
                    + f"\n\nCRITICAL SAFETY CONSTRAINT: The user has life-threatening allergies to: {allergen_list}. "
                    f"You MUST NOT include ANY ingredient containing {allergen_list}. "
                    f"Double-check every ingredient before including it. "
                    f"Violation of this constraint is dangerous."
                )
                retry_response = openai.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0.4,
                    messages=[
                        {"role": "system", "content": _GENERATE_SYSTEM},
                        {"role": "user", "content": retry_prompt},
                    ],
                )
                retry_raw = retry_response.choices[0].message.content.strip()
                if retry_raw.startswith("```"):
                    retry_raw = retry_raw.split("\n", 1)[1] if "\n" in retry_raw else retry_raw[3:]
                if retry_raw.endswith("```"):
                    retry_raw = retry_raw[:-3]
                retry_raw = retry_raw.strip()

                try:
                    retry_plan_data = json.loads(retry_raw)
                    retry_warnings = _validate_allergens(retry_plan_data, allergies)
                    if not retry_warnings:
                        # Second attempt is clean — use it
                        plan_data = retry_plan_data
                        allergen_warnings = []
                    else:
                        # Second attempt still has allergens — keep it but preserve warnings
                        plan_data = retry_plan_data
                        allergen_warnings = retry_warnings
                except json.JSONDecodeError:
                    logger.error("Failed to parse retry nutrition plan JSON; using first attempt.")

        now = datetime.now().isoformat(timespec="seconds")
        plan = {
            "plan_id": uuid.uuid4().hex[:8],
            "title": plan_data.get("title", "Nutrition Plan"),
            "created_at": now,
            "updated_at": now,
            "active": True,
            "duration_days": plan_data.get("duration_days", 7),
            "daily_targets": plan_data.get("daily_targets", {}),
            "days": plan_data.get("days", {}),
            "grocery_list": plan_data.get("grocery_list", []),
            "nutrient_alerts": [],
        }

        # Surface allergen warnings as prominent nutrient_alerts
        for w in allergen_warnings:
            plan["nutrient_alerts"].append({
                "nutrient": f"ALLERGEN: {w['allergen']}",
                "status": "high",
                "message": (
                    f"WARNING: '{w['allergen']}' found in {w['day']} / {w['meal']} "
                    f"(ingredient: {w['ingredient']}). Please substitute before consuming."
                ),
            })

        # Add nutrient alerts from profile
        if profile:
            from .nutrition_search import detect_nutrient_gaps
            gaps = detect_nutrient_gaps(profile, plan)
            plan["nutrient_alerts"].extend(gaps)

        return plan
    except json.JSONDecodeError as e:
        logger.error("Failed to parse nutrition plan JSON: %s", e)
        raise ValueError("Failed to generate a valid meal plan. Please try again with a different request.")
    except Exception as e:
        logger.error("Failed to generate nutrition plan: %s", e)
        raise


def modify_nutrition_plan(current_plan: dict, modification_request: str, username: str) -> dict:
    """Use LLM to modify an existing nutrition plan."""
    profile = _load_profile(username)

    try:
        current_json = json.dumps({
            "title": current_plan.get("title", ""),
            "daily_targets": current_plan.get("daily_targets", {}),
            "days": current_plan.get("days", {}),
            "grocery_list": current_plan.get("grocery_list", []),
        }, indent=2)

        prompt = (
            f"Current plan:\n{current_json}\n\n"
            f"Modification request: {modification_request}\n\n"
        )

        if profile:
            allergies = profile.get("allergies", [])
            if allergies:
                prompt += f"ALLERGIES (MUST AVOID): {', '.join(allergies)}\n"

        prompt += "Return the FULL updated plan JSON with the modification applied."

        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.5,
            messages=[
                {"role": "system", "content": _GENERATE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        plan_data = json.loads(raw)

        allergen_warnings: list[dict] = []
        if profile:
            allergies = profile.get("allergies", [])
            allergen_warnings = _validate_allergens(plan_data, allergies)

        current_plan["title"] = plan_data.get("title", current_plan.get("title", "Nutrition Plan"))
        current_plan["daily_targets"] = plan_data.get("daily_targets", current_plan.get("daily_targets", {}))
        current_plan["days"] = plan_data.get("days", current_plan.get("days", {}))
        current_plan["grocery_list"] = plan_data.get("grocery_list", current_plan.get("grocery_list", []))
        current_plan["updated_at"] = datetime.now().isoformat(timespec="seconds")

        # Surface allergen warnings in nutrient_alerts
        existing_alerts = [a for a in current_plan.get("nutrient_alerts", [])
                           if not a.get("nutrient", "").startswith("ALLERGEN:")]
        for w in allergen_warnings:
            existing_alerts.insert(0, {
                "nutrient": f"ALLERGEN: {w['allergen']}",
                "status": "high",
                "message": (
                    f"WARNING: '{w['allergen']}' found in {w['day']} / {w['meal']} "
                    f"(ingredient: {w['ingredient']}). Please substitute before consuming."
                ),
            })
        current_plan["nutrient_alerts"] = existing_alerts

        return current_plan
    except json.JSONDecodeError as e:
        logger.error("Failed to parse modified nutrition plan JSON: %s", e)
        raise ValueError("Failed to modify the meal plan. Please try again.")
    except Exception as e:
        logger.error("Failed to modify nutrition plan: %s", e)
        raise


def _validate_allergens(plan_data: dict, allergies: list[str]) -> list[dict]:
    """Post-generation validation: return list of allergen warnings found in the plan.

    Each warning is a dict with keys: allergen, day, meal, ingredient.
    Returns an empty list if no allergens are detected.
    """
    if not allergies:
        return []
    warnings: list[dict] = []
    allergen_set = {a.lower() for a in allergies}
    days = plan_data.get("days", {})
    for day_name, day_data in days.items():
        if not isinstance(day_data, dict):
            continue
        for meal in day_data.get("meals", []):
            for ingredient in meal.get("ingredients", []):
                ing_name = ingredient.get("name", "").lower()
                for allergen in allergen_set:
                    if allergen in ing_name:
                        logger.warning(
                            "Allergen '%s' found in plan day=%s meal=%s ingredient=%s",
                            allergen, day_name, meal.get("name", ""), ing_name,
                        )
                        warnings.append({
                            "allergen": allergen,
                            "day": day_name,
                            "meal": meal.get("name", "unknown"),
                            "ingredient": ing_name,
                        })
    return warnings


def get_plan_summary(plan: dict) -> str:
    """Return a concise text summary of the nutrition plan for chat display."""
    if not plan:
        return "No active nutrition plan found."
    title = plan.get("title", "Nutrition Plan")
    targets = plan.get("daily_targets", {})
    days = plan.get("days", {})
    alerts = plan.get("nutrient_alerts", [])

    lines = [f"**{title}**\n"]

    if targets:
        lines.append(
            f"Daily targets: {targets.get('calories', '?')} kcal | "
            f"P: {targets.get('protein_g', '?')}g | "
            f"C: {targets.get('carbs_g', '?')}g | "
            f"F: {targets.get('fat_g', '?')}g\n"
        )

    for day, data in days.items():
        if not isinstance(data, dict):
            continue
        meals = data.get("meals", [])
        meal_names = ", ".join(m.get("name", "?") for m in meals[:4])
        if len(meals) > 4:
            meal_names += f" +{len(meals) - 4} more"
        lines.append(f"- **{day.capitalize()}**: {meal_names}")

    if alerts:
        real_alerts = [a for a in alerts if a.get("status") != "unknown"]
        if real_alerts:
            lines.append("\n**Nutrient Alerts:**")
            for alert in real_alerts:
                lines.append(f"- {alert['nutrient']}: {alert['message']}")

    return "\n".join(lines)


def get_grocery_summary(plan: dict) -> str:
    """Return a formatted grocery list from the active plan."""
    if not plan:
        return "No active nutrition plan found."
    grocery = plan.get("grocery_list", [])
    if not grocery:
        return "No grocery list available for the current plan."

    lines = [f"**Grocery List for: {plan.get('title', 'Nutrition Plan')}**\n"]
    by_category: dict[str, list[dict]] = {}
    for item in grocery:
        cat = item.get("category", "other").replace("_", " ").title()
        by_category.setdefault(cat, []).append(item)

    total_cost = 0.0
    for cat in sorted(by_category.keys()):
        lines.append(f"\n**{cat}:**")
        for item in by_category[cat]:
            name = item.get("name", "?").title()
            amount = item.get("amount", "")
            cost = item.get("estimated_cost_usd")
            cost_str = f" (~${cost:.2f})" if cost else ""
            lines.append(f"- {name}: {amount}{cost_str}")
            if cost:
                total_cost += cost

    if total_cost > 0:
        lines.append(f"\n**Estimated total: ${total_cost:.2f}**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatch (called from agent.py)
# ---------------------------------------------------------------------------

def handle_nutrition_tool(action: str, details: str = "", username: str = "") -> str:
    """Dispatch manage_nutrition tool calls from the LLM."""
    if not username:
        return "Error: no user context available."

    if action == "view_plan":
        plan = _get_active_plan(username)
        return get_plan_summary(plan)

    elif action == "create_plan":
        profile = _load_profile(username)
        if not profile:
            return "Please set up your nutrition profile first. Tell me your age, weight, height, sex, activity level, any allergies, dietary preferences, and health goals."
        plan = generate_nutrition_plan(details or "Create a balanced 7-day meal plan", username)
        _set_active_plan(username, plan)
        return f"Meal plan created: **{plan['title']}**\n\n{get_plan_summary(plan)}"

    elif action == "modify_plan":
        plan = _get_active_plan(username)
        if not plan:
            return "No active nutrition plan to modify. Create one first."
        updated = modify_nutrition_plan(plan, details or "", username)
        _update_active_plan(username, updated)
        return f"Plan updated: **{updated['title']}**\n\n{get_plan_summary(updated)}"

    elif action == "grocery_list":
        plan = _get_active_plan(username)
        if not plan:
            return "No active nutrition plan. Create one first to get a grocery list."
        return get_grocery_summary(plan)

    elif action == "update_profile":
        profile = _load_profile(username) or dict(_DEFAULT_PROFILE)
        try:
            updates = json.loads(details) if details else {}
        except json.JSONDecodeError:
            updates = {}
        # Merge updates
        for key in _DEFAULT_PROFILE:
            if key in updates:
                if key == "lab_values" and isinstance(updates[key], dict):
                    existing_labs = profile.get("lab_values", dict(_DEFAULT_PROFILE["lab_values"]))
                    existing_labs.update(updates[key])
                    profile["lab_values"] = existing_labs
                else:
                    profile[key] = updates[key]
        _save_profile(username, profile)
        return f"Nutrition profile updated successfully.\n\nAge: {profile['age']} | Weight: {profile['weight_kg']}kg | Height: {profile['height_cm']}cm | Sex: {profile['sex']} | Activity: {profile['activity_level']}"

    elif action == "nutrient_check":
        profile = _load_profile(username)
        if not profile:
            return "Please set up your nutrition profile first."
        from .nutrition_search import detect_nutrient_gaps, compute_daily_targets
        plan = _get_active_plan(username)
        gaps = detect_nutrient_gaps(profile, plan)
        targets = compute_daily_targets(profile)
        lines = [
            f"**Daily Targets:** {targets['calories']} kcal | P: {targets['protein_g']}g | C: {targets['carbs_g']}g | F: {targets['fat_g']}g | Fiber: {targets['fiber_g']}g\n"
        ]
        if gaps:
            lines.append("**Nutrient Analysis:**")
            for gap in gaps:
                status_icon = "!" if gap["status"] in ("low", "high") else "?"
                lines.append(f"- [{status_icon}] {gap['nutrient']}: {gap['message']}")
                if gap.get("food_suggestions"):
                    lines.append(f"  Suggested foods: {', '.join(gap['food_suggestions'][:4])}")
        else:
            lines.append("No nutrient gaps detected based on available lab values.")
        return "\n".join(lines)

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@nutrition_bp.route("/nutrition")
def nutrition_page():
    if not _require_login():
        from flask import redirect, url_for
        return redirect(url_for("index"))
    return render_template("nutrition.html", username=session.get("username"))


@nutrition_bp.route("/api/nutrition-profile")
def api_get_profile():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    profile = _load_profile(_username())
    if not profile:
        return jsonify(success=True, profile=None)
    return jsonify(success=True, profile=profile)


_VALID_SEX = {"male", "female"}
_VALID_ACTIVITY = {"sedentary", "light", "moderate", "active", "very_active"}


def _validate_profile_fields(data: dict) -> dict:
    """Validate and coerce profile fields from raw request data.

    Only returns keys that are present in *data* AND in _DEFAULT_PROFILE,
    with proper type coercion and clamping applied.
    """
    validated: dict = {}

    if "age" in data:
        try:
            validated["age"] = max(1, min(120, int(data["age"])))
        except (TypeError, ValueError):
            validated["age"] = 30

    if "weight_kg" in data:
        try:
            validated["weight_kg"] = max(20.0, min(300.0, float(data["weight_kg"])))
        except (TypeError, ValueError):
            validated["weight_kg"] = 70.0

    if "height_cm" in data:
        try:
            validated["height_cm"] = max(50.0, min(250.0, float(data["height_cm"])))
        except (TypeError, ValueError):
            validated["height_cm"] = 170.0

    if "sex" in data:
        val = str(data["sex"]).lower().strip()
        validated["sex"] = val if val in _VALID_SEX else "male"

    if "activity_level" in data:
        val = str(data["activity_level"]).lower().strip()
        validated["activity_level"] = val if val in _VALID_ACTIVITY else "moderate"

    if "allergies" in data:
        raw = data["allergies"]
        if isinstance(raw, list):
            validated["allergies"] = [str(item) for item in raw if isinstance(item, (str, int, float))]
        else:
            validated["allergies"] = []

    if "dietary_preferences" in data:
        raw = data["dietary_preferences"]
        if isinstance(raw, list):
            validated["dietary_preferences"] = [str(item) for item in raw if isinstance(item, (str, int, float))]
        else:
            validated["dietary_preferences"] = []

    if "health_goals" in data:
        raw = data["health_goals"]
        if isinstance(raw, list):
            validated["health_goals"] = [str(item) for item in raw if isinstance(item, (str, int, float))]
        else:
            validated["health_goals"] = []

    if "weekly_budget_usd" in data:
        raw = data["weekly_budget_usd"]
        if raw is None:
            validated["weekly_budget_usd"] = None
        else:
            try:
                validated["weekly_budget_usd"] = max(0.0, min(10000.0, float(raw)))
            except (TypeError, ValueError):
                validated["weekly_budget_usd"] = None

    if "lab_values" in data:
        raw = data["lab_values"]
        if isinstance(raw, dict):
            clean_labs: dict = {}
            for k, v in raw.items():
                if v is None:
                    clean_labs[str(k)] = None
                else:
                    try:
                        clean_labs[str(k)] = float(v)
                    except (TypeError, ValueError):
                        clean_labs[str(k)] = None
            validated["lab_values"] = clean_labs
        # else: skip invalid lab_values entirely

    return validated


@nutrition_bp.route("/api/nutrition-profile", methods=["POST"])
def api_save_profile():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    profile = _load_profile(_username()) or dict(_DEFAULT_PROFILE)

    validated = _validate_profile_fields(data)
    for key, value in validated.items():
        if key == "lab_values" and isinstance(value, dict):
            existing_labs = profile.get("lab_values", dict(_DEFAULT_PROFILE["lab_values"]))
            existing_labs.update(value)
            profile["lab_values"] = existing_labs
        else:
            profile[key] = value

    _save_profile(_username(), profile)
    return jsonify(success=True, profile=profile)


@nutrition_bp.route("/api/nutrition-pantry")
def api_get_pantry():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    pantry = _load_pantry(_username())
    return jsonify(success=True, pantry=pantry)


@nutrition_bp.route("/api/nutrition-pantry", methods=["POST"])
def api_save_pantry():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    pantry = {"items": data.get("items", []), "updated_at": None}
    _save_pantry(_username(), pantry)
    return jsonify(success=True, pantry=pantry)


@nutrition_bp.route("/api/nutrition-plan")
def api_get_plan():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    plan = _get_active_plan(_username())
    if not plan:
        return jsonify(success=True, plan=None)
    return jsonify(success=True, plan=plan)


@nutrition_bp.route("/api/nutrition-plan", methods=["POST"])
def api_create_plan():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    profile = _load_profile(_username())
    if not profile:
        return jsonify(success=False, message="Please set up your nutrition profile first."), 400
    data = request.get_json(force=True)
    details = data.get("details", "Create a balanced 7-day meal plan")
    try:
        plan = generate_nutrition_plan(details, _username())
        _set_active_plan(_username(), plan)
        return jsonify(success=True, plan=plan)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@nutrition_bp.route("/api/nutrition-plan", methods=["PUT"])
def api_modify_plan():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    details = data.get("details", "")
    plan = _get_active_plan(_username())
    if not plan:
        return jsonify(success=False, message="No active plan"), 404
    try:
        updated = modify_nutrition_plan(plan, details, _username())
        _update_active_plan(_username(), updated)
        return jsonify(success=True, plan=updated)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@nutrition_bp.route("/api/nutrition-plan/grocery-list")
def api_grocery_list():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    plan = _get_active_plan(_username())
    if not plan:
        return jsonify(success=False, message="No active plan"), 404
    return jsonify(success=True, grocery_list=plan.get("grocery_list", []))


@nutrition_bp.route("/api/nutrition-plan/nutrient-gaps")
def api_nutrient_gaps():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    profile = _load_profile(_username())
    if not profile:
        return jsonify(success=False, message="Profile required"), 400
    from .nutrition_search import detect_nutrient_gaps
    plan = _get_active_plan(_username())
    gaps = detect_nutrient_gaps(profile, plan)
    return jsonify(success=True, gaps=gaps)

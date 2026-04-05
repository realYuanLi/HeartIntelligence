"""Workout plan persistence, CRUD API, LLM plan generation, and iCal export."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import openai
from dotenv import load_dotenv
from flask import Blueprint, jsonify, render_template, request, session, send_file
from flask_login import current_user, login_required

load_dotenv()

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
PLANS_DIR = APP_DIR / "personal_data" / "workout_plans"
PLANS_DIR.mkdir(parents=True, exist_ok=True)

calendar_bp = Blueprint("calendar", __name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _username() -> Optional[str]:
    if current_user.is_authenticated:
        return current_user.email
    return session.get("username")


def _require_login():
    return current_user.is_authenticated


def _plan_path(username: str) -> Path:
    return PLANS_DIR / f"{username}.json"


def _load_plans(username: str) -> list[dict]:
    p = _plan_path(username)
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        # Legacy single-plan format
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
    # Not found — append
    plans.append(updated_plan)
    _save_plans(username, plans)


# ---------------------------------------------------------------------------
# LLM Plan Generation
# ---------------------------------------------------------------------------

_PLAN_SCHEMA = {
    "title": "string — short descriptive title",
    "schedule": {
        "<day_of_week>": {
            "label": "string — session label",
            "exercises": [
                {
                    "name": "string — exercise name from database",
                    "sets": "int",
                    "reps": "string — e.g. '10-12' or '30s'",
                    "equipment": "string",
                    "image_path": "string or null"
                }
            ]
        }
    }
}

_GENERATE_SYSTEM = f"""You are a fitness plan generator. Return ONLY valid JSON matching this schema:
{json.dumps(_PLAN_SCHEMA, indent=2)}

Rules:
- schedule keys must be lowercase day names (monday, tuesday, etc.)
- Use real exercise names (e.g. "Dumbbell Bench Press", "Barbell Squat", "Pull-Up")
- image_path should be null (the system will fill it in)
- Typical plans have 3-5 training days per week
- Each day should have 4-6 exercises (keep it focused, not overwhelming)
- Include sets and reps appropriate for the requested level
- Plans cover ONE WEEK ONLY — never generate multi-week or repeating plans
- Return ONLY the JSON object, no markdown fences, no explanation."""


def generate_workout_plan(user_request: str) -> dict:
    """Use LLM to generate a workout plan from a user request."""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.7,
            messages=[
                {"role": "system", "content": _GENERATE_SYSTEM},
                {"role": "user", "content": user_request},
            ],
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        plan_data = json.loads(raw)

        # Fill in image paths from exercise database
        _fill_image_paths(plan_data.get("schedule", {}))

        now = datetime.now().isoformat(timespec="seconds")
        plan = {
            "plan_id": uuid.uuid4().hex[:8],
            "title": plan_data.get("title", "Workout Plan"),
            "created_at": now,
            "updated_at": now,
            "schedule": plan_data.get("schedule", {}),
            "completions": {},
            "active": True,
        }
        return plan
    except Exception as e:
        logger.error("Failed to generate workout plan: %s", e)
        raise


def modify_workout_plan(current_plan: dict, modification_request: str) -> dict:
    """Use LLM to modify an existing plan."""
    try:
        current_schedule = json.dumps(current_plan.get("schedule", {}), indent=2)
        prompt = (
            f"Current plan title: {current_plan.get('title', '')}\n"
            f"Current schedule:\n{current_schedule}\n\n"
            f"Modification request: {modification_request}\n\n"
            f"Return the FULL updated plan JSON (title + schedule) with the modification applied."
        )
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
        _fill_image_paths(plan_data.get("schedule", {}))

        current_plan["title"] = plan_data.get("title", current_plan.get("title", "Workout Plan"))
        current_plan["schedule"] = plan_data.get("schedule", current_plan.get("schedule", {}))
        current_plan["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return current_plan
    except Exception as e:
        logger.error("Failed to modify workout plan: %s", e)
        raise


def _fill_image_paths(schedule: dict):
    """Try to match exercise names to images in the exercise database."""
    try:
        from .workout_search import search_exercises
        for day_data in schedule.values():
            if not isinstance(day_data, dict):
                continue
            for ex in day_data.get("exercises", []):
                if ex.get("image_path"):
                    continue
                results = search_exercises(ex.get("name", ""), max_results=1)
                if results and results[0].get("images"):
                    ex["image_path"] = results[0]["images"][0]
    except Exception:
        pass


def mark_day_complete(username: str, date_str: str, completed: bool = True) -> Optional[dict]:
    """Toggle completion for a specific date."""
    plan = _get_active_plan(username)
    if not plan:
        return None

    if completed:
        plan["completions"][date_str] = {
            "completed": True,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        plan["completions"].pop(date_str, None)

    plan["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _update_active_plan(username, plan)
    return plan


def get_plan_summary(plan: dict) -> str:
    """Return a concise text summary of the plan for chat display."""
    if not plan:
        return "No active workout plan found."
    title = plan.get("title", "Workout Plan")
    schedule = plan.get("schedule", {})
    lines = [f"**{title}**\n"]
    for day, data in schedule.items():
        if not isinstance(data, dict):
            continue
        label = data.get("label", day.capitalize())
        exercises = data.get("exercises", [])
        ex_names = ", ".join(e.get("name", "?") for e in exercises[:4])
        if len(exercises) > 4:
            ex_names += f" +{len(exercises) - 4} more"
        lines.append(f"- **{day.capitalize()}** ({label}): {ex_names}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatch (called from agent.py)
# ---------------------------------------------------------------------------

def remove_exercise(username: str, day_name: str, exercise_name: str) -> Optional[dict]:
    """Remove an exercise from a specific day in the active plan."""
    plan = _get_active_plan(username)
    if not plan:
        return None

    schedule = plan.get("schedule", {})
    day_data = schedule.get(day_name)
    if not day_data or not isinstance(day_data, dict):
        return None

    exercises = day_data.get("exercises", [])
    original_len = len(exercises)
    day_data["exercises"] = [
        ex for ex in exercises if ex.get("name", "").lower() != exercise_name.lower()
    ]

    if len(day_data["exercises"]) == original_len:
        return None  # Nothing was removed

    # If day has no exercises left, remove the entire day from schedule
    if not day_data["exercises"]:
        del schedule[day_name]

    plan["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _update_active_plan(username, plan)
    return plan


def handle_workout_plan_tool(action: str, details: str = "", username: str = "") -> str:
    """Dispatch manage_workout_plan tool calls from the LLM."""
    if not username:
        return "Error: no user context available."

    if action == "view":
        plan = _get_active_plan(username)
        return get_plan_summary(plan)

    elif action == "create":
        plan = generate_workout_plan(details or "Create a balanced workout plan")
        _set_active_plan(username, plan)
        return f"Workout plan created: **{plan['title']}**\n\n{get_plan_summary(plan)}"

    elif action == "modify":
        plan = _get_active_plan(username)
        if not plan:
            return "No active workout plan to modify. Create one first."
        updated = modify_workout_plan(plan, details or "")
        _update_active_plan(username, updated)
        return f"Plan updated: **{updated['title']}**\n\n{get_plan_summary(updated)}"

    elif action == "complete_today":
        today = datetime.now().strftime("%Y-%m-%d")
        result = mark_day_complete(username, today, True)
        if result:
            return f"Marked today ({today}) as complete! Great work!"
        return "No active workout plan found."

    elif action == "complete_date":
        date_str = (details or "").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        result = mark_day_complete(username, date_str, True)
        if result:
            return f"Marked {date_str} as complete!"
        return "No active workout plan found."

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# iCal Export
# ---------------------------------------------------------------------------

def _generate_ical(plan: dict) -> str:
    """Generate an .ics file content from a workout plan."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//HeartIntelligence//Workout Plan//EN",
        "CALSCALE:GREGORIAN",
    ]

    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    }

    today = datetime.now().date()
    schedule = plan.get("schedule", {})

    for day_name, day_data in schedule.items():
        if not isinstance(day_data, dict):
            continue
        target_weekday = day_map.get(day_name.lower())
        if target_weekday is None:
            continue

        label = day_data.get("label", day_name.capitalize())
        exercises = day_data.get("exercises", [])
        description = "\\n".join(
            f"- {e.get('name', '?')}: {e.get('sets', '?')}x{e.get('reps', '?')}"
            for e in exercises
        )

        # Find the next occurrence of this weekday
        days_ahead = target_weekday - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
        start_date = today + timedelta(days=days_ahead)

        uid = f"{plan.get('plan_id', 'plan')}-{day_name}@heartintelligence"
        dtstart = start_date.strftime("%Y%m%d")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"SUMMARY:{label} - {plan.get('title', 'Workout')}",
            f"DESCRIPTION:{description}",
            f"RRULE:FREQ=WEEKLY;COUNT=1",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@calendar_bp.route("/calendar")
@login_required
def calendar_page():
    return render_template("calendar.html", username=_username())


@calendar_bp.route("/api/workout-plan")
def api_get_plan():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    plan = _get_active_plan(_username())
    if not plan:
        return jsonify(success=True, plan=None)
    return jsonify(success=True, plan=plan)


@calendar_bp.route("/api/workout-plan", methods=["POST"])
def api_create_plan():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    details = data.get("details", "Create a balanced workout plan")
    try:
        plan = generate_workout_plan(details)
        _set_active_plan(_username(), plan)
        return jsonify(success=True, plan=plan)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@calendar_bp.route("/api/workout-plan", methods=["PUT"])
def api_modify_plan():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    details = data.get("details", "")
    plan = _get_active_plan(_username())
    if not plan:
        return jsonify(success=False, message="No active plan"), 404
    try:
        updated = modify_workout_plan(plan, details)
        _update_active_plan(_username(), updated)
        return jsonify(success=True, plan=updated)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@calendar_bp.route("/api/workout-plan/complete", methods=["POST"])
def api_toggle_complete():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    date_str = data.get("date", "")
    completed = data.get("completed", True)
    if not date_str:
        return jsonify(success=False, message="Date required"), 400
    result = mark_day_complete(_username(), date_str, completed)
    if result:
        return jsonify(success=True, completions=result.get("completions", {}))
    return jsonify(success=False, message="No active plan"), 404


@calendar_bp.route("/api/workout-plan/exercise", methods=["DELETE"])
def api_delete_exercise():
    """Remove a single exercise from a day in the active plan."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    data = request.get_json(force=True)
    day = data.get("day", "").strip().lower()
    exercise_name = data.get("exercise_name", "").strip()
    if not day or not exercise_name:
        return jsonify(success=False, message="day and exercise_name required"), 400
    result = remove_exercise(_username(), day, exercise_name)
    if result:
        return jsonify(success=True, plan=result)
    return jsonify(success=False, message="Exercise not found or no active plan"), 404


@calendar_bp.route("/api/workout-plan/calendar")
def api_calendar_month():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    if not year or not month:
        now = datetime.now()
        year = year or now.year
        month = month or now.month

    plan = _get_active_plan(_username())
    schedule = plan.get("schedule", {}) if plan else {}
    completions = plan.get("completions", {}) if plan else {}

    # Build day-of-week lookup
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    # Generate each day of the month
    import calendar as cal_mod
    _, num_days = cal_mod.monthrange(year, month)
    days = []
    for d in range(1, num_days + 1):
        date_obj = datetime(year, month, d).date()
        date_str = date_obj.isoformat()
        weekday_name = day_names[date_obj.weekday()]

        day_info = {"date": date_str, "weekday": weekday_name}

        if weekday_name in schedule:
            sched = schedule[weekday_name]
            day_info["has_workout"] = True
            day_info["label"] = sched.get("label", weekday_name.capitalize())
            day_info["exercise_count"] = len(sched.get("exercises", []))
        else:
            day_info["has_workout"] = False

        if date_str in completions:
            day_info["completed"] = completions[date_str].get("completed", False)
        else:
            day_info["completed"] = False

        days.append(day_info)

    plan_info = None
    if plan:
        plan_info = {
            "plan_id": plan.get("plan_id"),
            "title": plan.get("title"),
        }
    return jsonify(success=True, days=days, plan=plan_info)


@calendar_bp.route("/api/workout-plan/exercise/<path:name>")
def api_exercise_details(name: str):
    """Get full exercise details on demand."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    try:
        from .workout_search import search_exercises, ensure_exercise_image
        results = search_exercises(name, max_results=1)
        if not results:
            return jsonify(success=False, message="Exercise not found"), 404
        ex = results[0]
        if ex.get("images"):
            ensure_exercise_image(ex["images"][0])
            ex["image_url"] = f"/exercises/images/{ex['images'][0]}"
        return jsonify(success=True, exercise=ex)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@calendar_bp.route("/api/workout-plan/export-ical")
def api_export_ical():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    plan = _get_active_plan(_username())
    if not plan:
        return jsonify(success=False, message="No active plan"), 404

    ical_content = _generate_ical(plan)
    import io
    buf = io.BytesIO(ical_content.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/calendar",
        as_attachment=True,
        download_name=f"workout-plan-{plan.get('plan_id', 'plan')}.ics",
    )

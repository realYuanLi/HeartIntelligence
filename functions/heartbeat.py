from __future__ import annotations

"""Heartbeat module for DREAM-Chat.

Proactive agent wake mechanism that periodically checks whether to
reach out to the user with timely, relevant information.  Runs inside
the existing cron scheduler loop.

Inspired by OpenClaw's heartbeat: a lightweight LLM triage call that
decides "send" or "suppress" based on assembled user context.
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config" / "heartbeat_config.json"
STATE_PATH = APP_DIR / "personal_data" / "cron_data" / "heartbeat_state.json"
SKILL_PATH = APP_DIR / "skills" / "heartbeat.md"

_DEFAULT_CONFIG = {
    "enabled": False,
    "interval_minutes": 30,
    "active_hours_start": "08:00",
    "active_hours_end": "22:00",
    "username": "",
    "delivery_method": "whatsapp",
    "target_jid": "",
    "target_session_id": "",
    "model": "gpt-4o-mini",
    "temperature": 0.3,
    "max_message_length": 500,
    "duplicate_window_hours": 24,
    "max_messages_per_day": 8,
}

_DEFAULT_STATE = {
    "last_run_at": None,
    "last_message_at": None,
    "last_message_preview": None,
    "messages_today": 0,
    "messages_today_date": None,
    "sent_hashes": [],
}


# ── Config / state persistence ──────────────────────────────────────────────

def load_config() -> dict:
    """Read heartbeat config, merged with defaults."""
    cfg = dict(_DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            logger.warning("Failed to read heartbeat config: %s", e)
    return cfg


def save_config(config: dict) -> None:
    """Persist heartbeat config."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_state() -> dict:
    """Read heartbeat state, merged with defaults."""
    state = dict(_DEFAULT_STATE)
    state["sent_hashes"] = []
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state.update(json.load(f))
        except Exception as e:
            logger.warning("Failed to read heartbeat state: %s", e)
    return state


def save_state(state: dict) -> None:
    """Persist heartbeat state."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Gate checks ─────────────────────────────────────────────────────────────

def _parse_time(hhmm: str) -> tuple[int, int]:
    """Parse 'HH:MM' -> (hour, minute)."""
    parts = hhmm.strip().split(":")
    return int(parts[0]), int(parts[1])


def _is_active_hours(now: datetime, start: str, end: str) -> bool:
    """Check if *now* falls within the active-hours window.

    Handles midnight-crossing ranges (e.g. start=22:00, end=06:00).
    """
    sh, sm = _parse_time(start)
    eh, em = _parse_time(end)
    start_mins = sh * 60 + sm
    end_mins = eh * 60 + em
    now_mins = now.hour * 60 + now.minute

    if start_mins <= end_mins:
        return start_mins <= now_mins < end_mins
    else:
        # crosses midnight
        return now_mins >= start_mins or now_mins < end_mins


def _should_run(config: dict, state: dict, now: datetime) -> bool:
    """Decide whether the heartbeat should fire this tick."""
    if not config.get("enabled"):
        return False

    if not _is_active_hours(now, config["active_hours_start"], config["active_hours_end"]):
        return False

    last_run = state.get("last_run_at")
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run)
            elapsed = (now - last_dt).total_seconds()
            if elapsed < config["interval_minutes"] * 60:
                return False
        except (ValueError, TypeError):
            pass

    return True


# ── Time-of-day awareness ───────────────────────────────────────────────────

def _get_time_window(now: datetime, start: str, end: str) -> str:
    """Classify the current moment into a time window for message-type guidance.

    Returns one of: "morning", "midday", "evening", or "night".
    Morning = first 2 hours of active window.
    Evening = last 2 hours of active window.
    """
    sh, sm = _parse_time(start)
    eh, em = _parse_time(end)
    start_mins = sh * 60 + sm
    end_mins = eh * 60 + em
    now_mins = now.hour * 60 + now.minute

    # Handle midnight-crossing by normalizing
    if start_mins > end_mins:
        # e.g. 22:00 to 06:00
        if now_mins >= start_mins:
            offset = now_mins - start_mins
        else:
            offset = (1440 - start_mins) + now_mins
        total = (1440 - start_mins) + end_mins
    else:
        offset = now_mins - start_mins
        total = end_mins - start_mins

    if total <= 0:
        return "midday"

    if offset < 120:
        return "morning"
    elif offset >= total - 120:
        return "evening"
    else:
        return "midday"


# ── Context assembly ────────────────────────────────────────────────────────

def _build_context(config: dict) -> str:
    """Assemble a rich context string for the heartbeat LLM call.

    Gathers data from multiple sources so the LLM can make an informed
    send/suppress decision. Each section is optional and fails silently.

    Sources: time-of-day awareness, user memory, pending reminders,
    calendar events, health data trends, active workout plan,
    nutrition goals, last user activity.

    Target: under ~1,500 tokens.
    """
    now = datetime.now()
    username = config.get("username", "")
    time_window = _get_time_window(
        now, config["active_hours_start"], config["active_hours_end"]
    )

    sections = [
        f"Current time: {now.strftime('%A, %B %d, %Y %I:%M %p')}",
        f"Time window: {time_window} (appropriate content: "
        + {
            "morning": "day preview, schedule reminders, gentle encouragement. NOT complex analysis.",
            "midday": "brief nudges about active plans, practical reminders. Keep it short.",
            "evening": "daily reflection, tomorrow prep, celebrate progress. NOT stressful observations.",
        }.get(time_window, "use your judgment.")
        + ")",
    ]

    # ── User memory (goals, preferences, health facts) ──────────────────
    if username:
        try:
            from functions.user_memory import UserMemory
            mem = UserMemory(username)
            summary = mem.get_summary(max_items=10)
            if summary:
                sections.append(f"USER MEMORY:\n{summary}")
        except Exception as e:
            logger.debug("Heartbeat: could not load user memory: %s", e)

    # ── Pending reminders (next 4 hours) ────────────────────────────────
    try:
        from functions.cron_jobs import _jobs, _lock
        upcoming = []
        cutoff = now + timedelta(hours=4)
        with _lock:
            for job in _jobs:
                if not job.get("enabled"):
                    continue
                if job["schedule_type"] == "once" and job.get("scheduled_at"):
                    try:
                        sched = datetime.fromisoformat(job["scheduled_at"])
                        if now <= sched <= cutoff and not job.get("last_executed_at"):
                            upcoming.append(f"- {sched.strftime('%I:%M %p')}: {job['message']}")
                    except (ValueError, TypeError):
                        pass
                elif job["schedule_type"] == "recurring" and job.get("time_of_day"):
                    h, m = map(int, job["time_of_day"].split(":"))
                    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if now <= t <= cutoff:
                        upcoming.append(f"- {t.strftime('%I:%M %p')}: {job['message']} (recurring)")
        if upcoming:
            sections.append("PENDING REMINDERS (next 4 hours):\n" + "\n".join(upcoming[:8]))
    except Exception as e:
        logger.debug("Heartbeat: could not load cron jobs: %s", e)

    # ── Upcoming calendar events (next 4 hours) ────────────────────────
    if username:
        try:
            from functions.external_calendar import get_upcoming_events, format_events_for_context
            events = get_upcoming_events(username, days_ahead=1)
            if events:
                cutoff_iso = (now + timedelta(hours=4)).isoformat()
                near = [e for e in events if e.get("start", "") <= cutoff_iso]
                if near:
                    formatted = format_events_for_context(near, max_events=6)
                    if formatted:
                        sections.append(f"UPCOMING CALENDAR (next 4 hours):\n{formatted}")
        except Exception as e:
            logger.debug("Heartbeat: could not load calendar: %s", e)

    # ── Health data trends (7-day) ─────────────────────────────────────
    try:
        health_summary = _gather_health_trends()
        if health_summary:
            sections.append(f"HEALTH DATA (7-day trends):\n{health_summary}")
    except Exception as e:
        logger.debug("Heartbeat: could not load health data: %s", e)

    # ── Active workout plan ────────────────────────────────────────────
    if username:
        try:
            workout_summary = _gather_workout_context(username, now)
            if workout_summary:
                sections.append(f"WORKOUT PLAN:\n{workout_summary}")
        except Exception as e:
            logger.debug("Heartbeat: could not load workout plan: %s", e)

    # ── Nutrition goals ────────────────────────────────────────────────
    if username:
        try:
            nutrition_summary = _gather_nutrition_context(username)
            if nutrition_summary:
                sections.append(f"NUTRITION GOALS:\n{nutrition_summary}")
        except Exception as e:
            logger.debug("Heartbeat: could not load nutrition data: %s", e)

    # ── Last user activity ─────────────────────────────────────────────
    if username:
        try:
            last_active = _get_last_user_activity(username)
            if last_active:
                sections.append(f"LAST USER ACTIVITY: {last_active}")
        except Exception as e:
            logger.debug("Heartbeat: could not check user activity: %s", e)

    # ── De-dup awareness ───────────────────────────────────────────────
    try:
        state = load_state()
        recent = state.get("sent_hashes", [])
        today_str = now.strftime("%Y-%m-%d")
        today_topics = []
        for h in recent:
            sent_dt = datetime.fromtimestamp(h.get("sent_at", 0))
            if sent_dt.strftime("%Y-%m-%d") == today_str:
                today_topics.append(h.get("topic", "unknown"))
        if today_topics:
            sections.append(
                f"TOPICS YOU ALREADY MESSAGED ABOUT TODAY: {', '.join(today_topics)}\n"
                f"Messages sent today: {len(today_topics)}"
            )
    except Exception:
        pass

    return "\n\n".join(sections)


# ── Context data gatherers ──────────────────────────────────────────────────

def _gather_health_trends() -> str:
    """Extract compact health trend summaries from mobile data.

    Returns a brief summary of notable 7-day trends (heart rate, BP,
    HRV, steps). Only includes data that exists and shows meaningful
    patterns. Keeps it compact for token efficiency.
    """
    mobile_data_path = APP_DIR / "personal_data" / "processed_mobile_data.json"
    if not mobile_data_path.exists():
        return ""

    try:
        with open(mobile_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""

    lines = []
    heart_data = data.get("heart_data", {})
    activity_data = data.get("activity_data", {})

    # Heart rate trend
    hr = heart_data.get("heart_rate", {})
    hr_stats = hr.get("daily_stats", [])
    if hr_stats:
        recent = hr_stats[-7:]
        if recent:
            avgs = [d.get("avg", 0) for d in recent if d.get("avg")]
            if avgs:
                avg_hr = sum(avgs) / len(avgs)
                trend = hr.get("trends", {}).get("trend", "")
                line = f"- Heart rate: 7-day avg {avg_hr:.0f} bpm"
                if trend:
                    line += f" ({trend})"
                lines.append(line)

    # Blood pressure trend
    bp = heart_data.get("blood_pressure", {})
    bp_readings = bp.get("readings", [])
    if bp_readings:
        recent_bp = bp_readings[:7]
        sys_vals = [r.get("systolic", 0) for r in recent_bp if r.get("systolic")]
        dia_vals = [r.get("diastolic", 0) for r in recent_bp if r.get("diastolic")]
        if sys_vals and dia_vals:
            avg_sys = sum(sys_vals) / len(sys_vals)
            avg_dia = sum(dia_vals) / len(dia_vals)
            line = f"- Blood pressure: 7-day avg {avg_sys:.0f}/{avg_dia:.0f} mmHg"
            bp_trends = bp.get("trends", {})
            if bp_trends.get("systolic_trend"):
                line += f" (systolic {bp_trends['systolic_trend']})"
            lines.append(line)

    # HRV trend
    hrv = heart_data.get("hrv", {})
    hrv_stats = hrv.get("daily_averages", [])
    if hrv_stats:
        recent_hrv = hrv_stats[-7:]
        hrv_avgs = [d.get("avg", 0) for d in recent_hrv if d.get("avg")]
        if hrv_avgs:
            avg_hrv = sum(hrv_avgs) / len(hrv_avgs)
            trend = hrv.get("trends", {}).get("trend", "")
            line = f"- HRV: 7-day avg {avg_hrv:.0f} ms"
            if trend:
                line += f" ({trend})"
            lines.append(line)

    # Step count trend
    steps_data = activity_data.get("daily_steps", [])
    if steps_data:
        recent_steps = steps_data[-7:]
        counts = [d.get("sum", 0) for d in recent_steps if d.get("sum")]
        if counts:
            avg_steps = sum(counts) / len(counts)
            # Calculate streak of days above 10k
            streak = 0
            for c in reversed(counts):
                if c >= 10000:
                    streak += 1
                else:
                    break
            line = f"- Steps: 7-day avg {avg_steps:,.0f}/day"
            if streak >= 3:
                line += f" ({streak}-day streak above 10k!)"
            elif counts and counts[-1] < avg_steps * 0.5:
                line += f" (today notably low: {counts[-1]:,.0f})"
            lines.append(line)

    return "\n".join(lines)


def _gather_workout_context(username: str, now: datetime) -> str:
    """Get today's workout schedule and recent completion status."""
    try:
        from functions.workout_plans import _get_active_plan
    except ImportError:
        return ""

    plan = _get_active_plan(username)
    if not plan:
        return ""

    schedule = plan.get("schedule", {})
    completions = plan.get("completions", {})
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    today_name = day_names[now.weekday()]
    today_str = now.strftime("%Y-%m-%d")

    lines = [f"Plan: {plan.get('title', 'Workout Plan')}"]

    # Today's schedule
    today_sched = schedule.get(today_name, {})
    if isinstance(today_sched, dict):
        label = today_sched.get("label", today_name.capitalize())
        exercises = today_sched.get("exercises", [])
        if exercises:
            ex_names = ", ".join(e.get("name", "?") for e in exercises[:4])
            completed = completions.get(today_str, {}).get("completed", False)
            status = "COMPLETED" if completed else "NOT YET DONE"
            lines.append(f"Today ({today_name.capitalize()}): {label} -- {ex_names} [{status}]")
        else:
            lines.append(f"Today ({today_name.capitalize()}): Rest day")

    # This week's completion rate
    week_start = now - timedelta(days=now.weekday())
    completed_this_week = 0
    workout_days_this_week = 0
    for i in range(min(now.weekday() + 1, 7)):
        d = week_start + timedelta(days=i)
        d_name = day_names[d.weekday()]
        d_sched = schedule.get(d_name, {})
        if isinstance(d_sched, dict) and d_sched.get("exercises"):
            workout_days_this_week += 1
            if completions.get(d.strftime("%Y-%m-%d"), {}).get("completed"):
                completed_this_week += 1

    if workout_days_this_week > 0:
        lines.append(f"This week: {completed_this_week}/{workout_days_this_week} workouts completed")

    return "\n".join(lines)


def _gather_nutrition_context(username: str) -> str:
    """Get nutrition profile goals for context."""
    profile_path = APP_DIR / "personal_data" / "nutrition_profiles" / f"{username}.json"
    if not profile_path.exists():
        return ""

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return ""

    lines = []
    goals = profile.get("health_goals", [])
    if goals:
        lines.append(f"Goals: {', '.join(goals)}")
    prefs = profile.get("dietary_preferences", [])
    if prefs:
        lines.append(f"Diet: {', '.join(prefs)}")
    allergies = profile.get("allergies", [])
    if allergies:
        lines.append(f"Allergies: {', '.join(allergies)}")

    return "\n".join(lines)


def _get_last_user_activity(username: str) -> str:
    """Check when the user last interacted with the chat.

    Returns a human-readable time delta like "12 minutes ago" or "3 hours ago".
    Returns empty string if unknown.
    """
    user_dir = APP_DIR / "chat_history" / username
    if not user_dir.exists():
        return ""

    try:
        # Find the most recently modified session file
        latest_mtime = 0.0
        for f in user_dir.iterdir():
            if f.suffix == ".json":
                mt = f.stat().st_mtime
                if mt > latest_mtime:
                    latest_mtime = mt
        if latest_mtime == 0:
            return ""

        last_dt = datetime.fromtimestamp(latest_mtime)
        delta = datetime.now() - last_dt
        mins = int(delta.total_seconds() / 60)

        if mins < 5:
            return "just now (user is currently active -- probably don't interrupt)"
        elif mins < 30:
            return f"{mins} minutes ago (recently active -- be cautious about interrupting)"
        elif mins < 60:
            return f"{mins} minutes ago"
        elif mins < 1440:
            hours = mins // 60
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = mins // 1440
            return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return ""


# ── Heartbeat instructions ──────────────────────────────────────────────────

def _load_heartbeat_instructions() -> str:
    """Read skills/heartbeat.md, strip frontmatter, return body."""
    if not SKILL_PATH.exists():
        return "Decide if there is something worth messaging the user about. Return JSON."
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Strip YAML frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].strip()
    return text


# ── Duplicate suppression ───────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    """Normalize text and return first 16 chars of SHA-256."""
    normalized = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _is_duplicate(msg_hash: str, state: dict, window_hours: int) -> bool:
    """Check if this hash was already sent within the window."""
    if window_hours <= 0:
        return False
    cutoff = time.time() - window_hours * 3600
    for entry in state.get("sent_hashes", []):
        if entry.get("hash") == msg_hash and entry.get("sent_at", 0) > cutoff:
            return True
    return False


def _check_daily_limit(state: dict, config: dict, now: datetime) -> bool:
    """Return True if we are still under the daily message limit."""
    today = now.strftime("%Y-%m-%d")
    if state.get("messages_today_date") != today:
        state["messages_today"] = 0
        state["messages_today_date"] = today
    return state["messages_today"] < config["max_messages_per_day"]


# ── LLM call ────────────────────────────────────────────────────────────────

def _call_llm(system_prompt: str, user_prompt: str, model: str, temperature: float) -> dict | None:
    """Make a lightweight OpenAI call and parse the JSON response."""
    try:
        import openai
        resp = openai.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            raw = raw.strip()

        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Heartbeat: LLM returned non-JSON: %s", raw[:200] if 'raw' in dir() else "?")
        return None
    except Exception as e:
        logger.error("Heartbeat LLM call failed: %s", e)
        return None


# ── Delivery ────────────────────────────────────────────────────────────────

def _deliver_message(message: str, config: dict) -> None:
    """Route the heartbeat message to the configured delivery channel."""
    delivery = config.get("delivery_method", "whatsapp")

    if delivery == "whatsapp":
        target_jid = config.get("target_jid", "")
        if not target_jid:
            logger.warning("Heartbeat: no target_jid configured for WhatsApp delivery")
            return
        from functions.cron_jobs import queue_outbound_message
        queue_outbound_message(target_jid, message, job_id="heartbeat", skip_prefix=True)
        logger.info("Heartbeat: queued WhatsApp message to %s", target_jid)

        # Also write to the shared web session so it appears in the web UI
        username = config.get("username", "")
        if username:
            try:
                # Use direct file I/O (no DB context needed)
                user_dir = APP_DIR / "chat_history" / username
                smap_path = user_dir / "_wa_session_map.json"
                if smap_path.exists():
                    with open(smap_path, "r", encoding="utf-8") as f:
                        smap = json.load(f)
                    entry = smap.get(target_jid)
                    if entry:
                        sid = entry.get("session_id") if isinstance(entry, dict) else entry
                        session_path = user_dir / f"{sid}.json"
                        if session_path.exists():
                            with open(session_path, "r", encoding="utf-8") as f:
                                d = json.load(f)
                            d["conversation"].append({"role": "assistant", "content": message})
                            d["updated_at"] = datetime.now().isoformat(timespec="seconds")
                            with open(session_path, "w", encoding="utf-8") as f:
                                json.dump(d, f, indent=2, ensure_ascii=False)
                            logger.info("Heartbeat: synced message to web session %s", sid)
            except Exception as e:
                logger.debug("Heartbeat: web session sync failed: %s", e)
    elif delivery == "web":
        username = config.get("username", "")
        session_id = config.get("target_session_id", "")
        if not username or not session_id:
            logger.warning("Heartbeat: no username/session_id for web delivery")
            return
        try:
            from app import _load_session, _save_session
            d = _load_session(username, session_id)
            if not d:
                logger.warning("Heartbeat: session %s not found", session_id)
                return
            d["conversation"].append({"role": "assistant", "content": message})
            d["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _save_session(username, d)
            logger.info("Heartbeat: delivered web message to %s/%s", username, session_id)
        except Exception as e:
            logger.error("Heartbeat web delivery failed: %s", e)
    else:
        logger.warning("Heartbeat: unknown delivery method '%s'", delivery)


# ── Main entry point ────────────────────────────────────────────────────────

def run_heartbeat() -> None:
    """Check if heartbeat should fire, and if so, run the triage LLM call.

    Called from ``_scheduler_loop`` on every tick (~30 seconds).
    Returns quickly on most ticks (just a timestamp comparison).
    """
    now = datetime.now()
    config = load_config()
    state = load_state()

    if not _should_run(config, state, now):
        return

    # Mark this tick as a run (even if we suppress)
    state["last_run_at"] = now.isoformat(timespec="seconds")

    # ── TESTING MODE: bypass LLM, dedup, and daily limit entirely ─────
    if config.get("testing_mode"):
        message = f"Heartbeat test at {now.strftime('%H:%M:%S')} — delivery pipeline is working!"
        _deliver_message(message, config)
        state["last_message_at"] = now.isoformat(timespec="seconds")
        state["last_message_preview"] = message[:100]
        state["messages_today"] = state.get("messages_today", 0) + 1
        save_state(state)
        logger.info("Heartbeat: TESTING MODE — sent test message")
        return
    # ── END TESTING MODE ──────────────────────────────────────────────

    # Check daily limit
    if not _check_daily_limit(state, config, now):
        logger.debug("Heartbeat: daily message limit reached (%d)", config["max_messages_per_day"])
        save_state(state)
        return

    # Build context
    context = _build_context(config)
    instructions = _load_heartbeat_instructions()

    # Call LLM
    logger.info("Heartbeat: running triage LLM call")
    result = _call_llm(
        system_prompt=instructions,
        user_prompt=context,
        model=config.get("model", "gpt-4o-mini"),
        temperature=config.get("temperature", 0.3),
    )

    if not result:
        save_state(state)
        return

    action = result.get("action", "suppress")

    if action == "send":
        message = (result.get("message") or "").strip()
        topic = (result.get("topic") or "check-in").strip()

        if not message:
            logger.debug("Heartbeat: LLM returned send with empty message, suppressing")
            save_state(state)
            return

        # Truncate if needed
        max_len = config.get("max_message_length", 500)
        if len(message) > max_len:
            # Truncate at word boundary
            message = message[:max_len].rsplit(" ", 1)[0] + "..."

        # Check for duplicates
        msg_hash = _content_hash(message)
        if _is_duplicate(msg_hash, state, config["duplicate_window_hours"]):
            logger.debug("Heartbeat: duplicate message suppressed (topic: %s)", topic)
            save_state(state)
            return

        # Deliver
        _deliver_message(message, config)

        # Update state
        state["last_message_at"] = now.isoformat(timespec="seconds")
        state["last_message_preview"] = message[:100]
        state["messages_today"] += 1
        state["sent_hashes"].append({
            "hash": msg_hash,
            "topic": topic,
            "sent_at": time.time(),
        })

        # Prune old hashes (keep last 50)
        state["sent_hashes"] = state["sent_hashes"][-50:]

        logger.info("Heartbeat: sent message (topic: %s, daily count: %d)", topic, state["messages_today"])
    else:
        reason = result.get("reason", "no reason given")
        logger.debug("Heartbeat: suppressed (%s)", reason)

    save_state(state)


def get_heartbeat_status() -> dict:
    """Return a status summary for the API."""
    config = load_config()
    state = load_state()
    now = datetime.now()

    # Calculate next run estimate
    next_run_in_minutes = None
    if config.get("enabled") and state.get("last_run_at"):
        try:
            last_dt = datetime.fromisoformat(state["last_run_at"])
            next_dt = last_dt + timedelta(minutes=config["interval_minutes"])
            remaining = (next_dt - now).total_seconds() / 60
            next_run_in_minutes = max(0, round(remaining))
        except (ValueError, TypeError):
            pass

    return {
        "enabled": config.get("enabled", False),
        "last_run_at": state.get("last_run_at"),
        "last_message_at": state.get("last_message_at"),
        "last_message_preview": state.get("last_message_preview"),
        "messages_today": state.get("messages_today", 0),
        "next_run_in_minutes": next_run_in_minutes,
    }

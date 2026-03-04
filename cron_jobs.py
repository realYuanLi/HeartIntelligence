"""Cron Jobs blueprint for DREAM-Chat.

Manages scheduled proactive messages sent to users via WhatsApp or web chat.
Jobs can be created manually through the dashboard or automatically
via natural language in chat (e.g. "remind me in 1 hour about X").

Reminder extraction uses an LLM call so it handles any phrasing, not
just a fixed set of regex patterns.

A background scheduler thread checks pending jobs every 30 seconds
and delivers via WhatsApp (outbound queue) or web chat (session append).
"""

import json
import logging
import threading
import time
import uuid
import re
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, request, render_template, redirect, url_for

cron_bp = Blueprint("cron_jobs", __name__)
logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "chat_history"
CRON_DIR = APP_DIR / "cron_data"
JOBS_PATH = CRON_DIR / "jobs.json"
OUTBOUND_PATH = CRON_DIR / "outbound_queue.json"

CRON_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory state ──────────────────────────────────────────────────────────

_jobs: list[dict] = []
_outbound_queue: list[dict] = []
_lock = threading.Lock()
_scheduler_running = False


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Persistence ──────────────────────────────────────────────────────────────

def _load_jobs() -> None:
    global _jobs
    if JOBS_PATH.exists():
        with open(JOBS_PATH, "r", encoding="utf-8") as f:
            _jobs = json.load(f)
    else:
        _jobs = []


def _save_jobs() -> None:
    CRON_DIR.mkdir(parents=True, exist_ok=True)
    with open(JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(_jobs, f, indent=2, ensure_ascii=False)


def _load_outbound() -> None:
    global _outbound_queue
    if OUTBOUND_PATH.exists():
        with open(OUTBOUND_PATH, "r", encoding="utf-8") as f:
            _outbound_queue = json.load(f)
    else:
        _outbound_queue = []


def _save_outbound() -> None:
    CRON_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTBOUND_PATH, "w", encoding="utf-8") as f:
        json.dump(_outbound_queue, f, indent=2, ensure_ascii=False)


# ── Job helpers ──────────────────────────────────────────────────────────────

def create_job(
    message: str,
    target_jid: str = "",
    schedule_type: str = "once",
    scheduled_at: str | None = None,
    frequency: str | None = None,
    time_of_day: str | None = None,
    day_of_week: str | None = None,
    created_by: str = "dashboard",
    user: str = "",
    delivery_method: str = "whatsapp",
    target_session_id: str = "",
) -> dict:
    """Create a new cron job and persist it.

    delivery_method: "whatsapp" (queue outbound WA message) or "web" (append
    to the user's chat session).
    """
    job = {
        "job_id": uuid.uuid4().hex[:12],
        "user": user,
        "target_jid": target_jid,
        "message": message,
        "schedule_type": schedule_type,
        "scheduled_at": scheduled_at,
        "frequency": frequency,
        "time_of_day": time_of_day,
        "day_of_week": day_of_week,
        "enabled": True,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "last_executed_at": None,
        "created_from": created_by,
        "delivery_method": delivery_method,
        "target_session_id": target_session_id,
    }
    with _lock:
        _jobs.append(job)
        _save_jobs()
    target = target_jid or f"web:{user}/{target_session_id}"
    logger.info("Created cron job %s → %s [%s]", job["job_id"], target, delivery_method)
    return job


def queue_outbound_message(target_jid: str, message: str, job_id: str = "") -> dict:
    """Queue a message for delivery to a WhatsApp user."""
    msg = {
        "msg_id": uuid.uuid4().hex[:12],
        "target_jid": target_jid,
        "message": message,
        "job_id": job_id,
        "created_at": _now_iso(),
        "status": "pending",
    }
    with _lock:
        _outbound_queue.append(msg)
        _save_outbound()
    logger.info("Queued outbound message %s for %s", msg["msg_id"], target_jid)
    return msg


# ── Scheduler ────────────────────────────────────────────────────────────────

def _should_execute_job(job: dict, now: datetime) -> bool:
    """Determine if a job should fire right now."""
    if not job.get("enabled"):
        return False

    if job["schedule_type"] == "once":
        if not job.get("scheduled_at"):
            return False
        scheduled = datetime.fromisoformat(job["scheduled_at"])
        if job.get("last_executed_at"):
            return False
        return now >= scheduled

    if job["schedule_type"] == "recurring":
        if not job.get("time_of_day"):
            return False

        hour, minute = map(int, job["time_of_day"].split(":"))
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        last_exec = job.get("last_executed_at")
        if last_exec:
            last_exec_dt = datetime.fromisoformat(last_exec)
        else:
            last_exec_dt = datetime.min

        freq = job.get("frequency", "daily")

        if freq == "hourly":
            target_time = now.replace(minute=minute, second=0, microsecond=0)
            if now < target_time:
                return False
            return (now - last_exec_dt).total_seconds() >= 3600

        if freq == "daily":
            if now < target_time:
                return False
            return last_exec_dt.date() < now.date()

        if freq == "weekly":
            dow = (job.get("day_of_week") or "monday").lower()
            day_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2,
                "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            }
            target_dow = day_map.get(dow, 0)
            if now.weekday() != target_dow:
                return False
            if now < target_time:
                return False
            return (now - last_exec_dt).days >= 1

    return False


def _execute_job(job: dict) -> None:
    """Fire a cron job via the appropriate delivery channel.

    MUST be called WITHOUT holding ``_lock`` — the delivery helpers
    acquire ``_lock`` themselves when writing to the outbound queue.
    """
    delivery = job.get("delivery_method", "whatsapp")

    if delivery == "web":
        _deliver_web_reminder(job)
    else:
        queue_outbound_message(job["target_jid"], job["message"], job["job_id"])

    logger.info("Executed cron job %s [%s]", job["job_id"], delivery)


def _deliver_web_reminder(job: dict) -> None:
    """Append a reminder message to the user's web chat session."""
    user = job.get("user", "")
    session_id = job.get("target_session_id", "")
    if not user or not session_id:
        logger.warning("Web reminder %s missing user/session_id, skipping", job["job_id"])
        return

    try:
        from app import _load_session, _save_session
        d = _load_session(user, session_id)
        if not d:
            logger.warning("Web reminder %s: session %s not found", job["job_id"], session_id)
            return

        reminder_msg = f"⏰ **Reminder:** {job['message']}"
        d["conversation"].append({"role": "assistant", "content": reminder_msg})
        d["updated_at"] = _now_iso()
        _save_session(user, d)
        logger.info("Web reminder delivered to %s/%s", user, session_id)
    except Exception as e:
        logger.error("Failed to deliver web reminder %s: %s", job["job_id"], e)


def _scheduler_loop() -> None:
    """Background loop that checks and fires cron jobs every 30 seconds.

    To avoid deadlocks, the pattern is:
      1. Hold ``_lock`` → identify which jobs should fire, mark them.
      2. Release ``_lock``.
      3. Execute side-effects (queue WA messages / web delivery) lock-free.
    """
    global _scheduler_running
    _scheduler_running = True
    logger.info("Cron job scheduler started")

    while _scheduler_running:
        try:
            now = datetime.now()
            to_execute: list[dict] = []

            with _lock:
                for job in _jobs:
                    if _should_execute_job(job, now):
                        job["last_executed_at"] = _now_iso()
                        job["updated_at"] = _now_iso()
                        if job["schedule_type"] == "once":
                            job["enabled"] = False
                        to_execute.append(job)
                if to_execute:
                    _save_jobs()

            for job in to_execute:
                try:
                    _execute_job(job)
                except Exception as e:
                    logger.error("Error executing job %s: %s", job["job_id"], e)
        except Exception as e:
            logger.error("Scheduler error: %s", e, exc_info=True)

        time.sleep(30)


def start_scheduler() -> None:
    """Start the background scheduler thread."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    global _scheduler_running
    _scheduler_running = False


# ── LLM-based reminder extraction ────────────────────────────────────────────

_REMINDER_SYSTEM_PROMPT = (
    "You are a reminder-extraction assistant. "
    "Given a user message and the current date/time, determine whether the "
    "message contains a request to be reminded or notified about something "
    "at a future time.\n\n"
    "Return ONLY a valid JSON object (no markdown fences, no explanation).\n\n"
    "If the message IS a reminder request:\n"
    '{"is_reminder":true,"delay_minutes":<int>,"reminder_text":"<what to remind about>"}\n\n'
    "delay_minutes = how many minutes from NOW the reminder should fire.\n"
    "reminder_text = a concise description of what to remind about.\n\n"
    "If the message is NOT a reminder request:\n"
    '{"is_reminder":false}\n\n'
    "Examples:\n"
    '  User (now 14:00): "remind me in 2 hours to take pills"\n'
    '  → {"is_reminder":true,"delay_minutes":120,"reminder_text":"take pills"}\n\n'
    '  User (now 22:00): "ping me tomorrow morning about the lab results"\n'
    '  → {"is_reminder":true,"delay_minutes":660,"reminder_text":"lab results"}\n\n'
    '  User: "what is my heart rate?"\n'
    '  → {"is_reminder":false}\n\n'
    '  User (now 10:00): "don\'t let me forget to exercise at 3pm"\n'
    '  → {"is_reminder":true,"delay_minutes":300,"reminder_text":"exercise"}\n\n'
    '  User (now 09:00): "can you check on me every day at 8am about my medication?"\n'
    '  → {"is_reminder":true,"delay_minutes":1380,"reminder_text":"medication check"}\n'
)

def parse_reminder_with_llm(text: str) -> dict | None:
    """Use a direct OpenAI call to detect reminder intent in *text*.

    Bypasses the Agent class (which runs health analysis / web search)
    and makes a lightweight chat completion request.

    Returns ``{"delay_minutes": int, "reminder_text": str}`` on success,
    or ``None`` when the message has no reminder intent.
    """
    now = datetime.now()
    prompt = (
        f"Current date/time: {now.strftime('%A, %B %d, %Y %I:%M %p')}\n"
        f"User message: {text}"
    )

    try:
        import openai
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": _REMINDER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content.strip()

        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            raw = raw.strip()

        data = json.loads(raw)
        if not data.get("is_reminder"):
            return None

        delay = int(data.get("delay_minutes", 0))
        reminder_text = (data.get("reminder_text") or "").strip() or "Scheduled reminder"
        if delay < 1:
            return None

        logger.info("LLM extracted reminder: delay=%d min, text='%s'", delay, reminder_text)
        return {"delay_minutes": delay, "reminder_text": reminder_text}
    except Exception as e:
        logger.error("LLM reminder extraction failed: %s", e)
        return None


def create_reminder_from_chat(
    user_message: str,
    user: str = "",
    sender_jid: str = "",
    session_id: str = "",
) -> dict | None:
    """Parse a chat message for reminder intent and create a cron job.

    Supports both WhatsApp (sender_jid) and web chat (user + session_id).
    Returns the created job dict, or None if no reminder was detected.
    """
    parsed = parse_reminder_with_llm(user_message)
    if not parsed:
        return None

    scheduled_at = (
        datetime.now() + timedelta(minutes=parsed["delay_minutes"])
    ).isoformat(timespec="seconds")

    if sender_jid:
        job = create_job(
            message=parsed["reminder_text"],
            target_jid=sender_jid,
            schedule_type="once",
            scheduled_at=scheduled_at,
            created_by="chat",
            user=user,
            delivery_method="whatsapp",
        )
    else:
        job = create_job(
            message=parsed["reminder_text"],
            schedule_type="once",
            scheduled_at=scheduled_at,
            created_by="chat",
            user=user,
            delivery_method="web",
            target_session_id=session_id,
        )
    return job


# ── Flask routes ─────────────────────────────────────────────────────────────

def _require_login() -> bool:
    from flask import session as flask_session
    from app import USERS
    u = flask_session.get("username")
    return bool(u and u in USERS)


def _username() -> str | None:
    from flask import session as flask_session
    return flask_session.get("username")


@cron_bp.route("/cron-jobs")
def cron_jobs_page():
    """Render the cron jobs dashboard page."""
    if not _require_login():
        return redirect(url_for("index"))
    from flask import session as flask_session
    return render_template("cron_jobs.html", username=flask_session.get("username"))


@cron_bp.route("/api/cron-jobs")
def api_list_jobs():
    """List all cron jobs."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    with _lock:
        return jsonify(success=True, jobs=list(_jobs))


@cron_bp.route("/api/cron-jobs", methods=["POST"])
def api_create_job():
    """Create a new cron job."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    target_jid = (data.get("target_jid") or "").strip()
    schedule_type = data.get("schedule_type", "once")
    scheduled_at = data.get("scheduled_at")
    frequency = data.get("frequency")
    time_of_day = data.get("time_of_day")
    day_of_week = data.get("day_of_week")

    if not message:
        return jsonify(success=False, message="Message is required"), 400
    if not target_jid:
        return jsonify(success=False, message="Target WhatsApp contact is required"), 400

    # Normalize JID
    if not target_jid.endswith("@s.whatsapp.net"):
        cleaned = re.sub(r"\D", "", target_jid)
        if cleaned:
            target_jid = f"{cleaned}@s.whatsapp.net"
        else:
            return jsonify(success=False, message="Invalid phone number"), 400

    job = create_job(
        message=message,
        target_jid=target_jid,
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        frequency=frequency,
        time_of_day=time_of_day,
        day_of_week=day_of_week,
        created_by="dashboard",
        user=_username() or "",
    )

    return jsonify(success=True, job=job)


@cron_bp.route("/api/cron-jobs/<job_id>", methods=["PUT"])
def api_update_job(job_id: str):
    """Update an existing cron job."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json(force=True)

    with _lock:
        for job in _jobs:
            if job["job_id"] == job_id:
                for key in ("message", "schedule_type", "scheduled_at",
                            "frequency", "time_of_day", "day_of_week",
                            "enabled", "target_jid"):
                    if key in data:
                        job[key] = data[key]
                if data.get("scheduled_at") or data.get("schedule_type"):
                    job["last_executed_at"] = None
                    job["enabled"] = data.get("enabled", True)
                job["updated_at"] = _now_iso()
                _save_jobs()
                return jsonify(success=True, job=job)

    return jsonify(success=False, message="Job not found"), 404


@cron_bp.route("/api/cron-jobs/<job_id>", methods=["DELETE"])
def api_delete_job(job_id: str):
    """Delete a cron job."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    with _lock:
        for i, job in enumerate(_jobs):
            if job["job_id"] == job_id:
                _jobs.pop(i)
                _save_jobs()
                return jsonify(success=True)

    return jsonify(success=False, message="Job not found"), 404


@cron_bp.route("/api/cron-jobs/<job_id>/toggle", methods=["POST"])
def api_toggle_job(job_id: str):
    """Toggle a cron job's enabled state."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    with _lock:
        for job in _jobs:
            if job["job_id"] == job_id:
                job["enabled"] = not job["enabled"]
                job["updated_at"] = _now_iso()
                _save_jobs()
                return jsonify(success=True, enabled=job["enabled"])

    return jsonify(success=False, message="Job not found"), 404


# ── Outbound queue endpoints (polled by WhatsApp bridge) ─────────────────────

@cron_bp.route("/api/whatsapp/outbound")
def api_outbound_queue():
    """Return pending outbound messages for the WhatsApp bridge to send."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    with _lock:
        pending = [m for m in _outbound_queue if m["status"] == "pending"]
    return jsonify(success=True, messages=pending)


@cron_bp.route("/api/whatsapp/outbound/<msg_id>/ack", methods=["POST"])
def api_outbound_ack(msg_id: str):
    """Mark an outbound message as delivered."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    with _lock:
        for msg in _outbound_queue:
            if msg["msg_id"] == msg_id:
                msg["status"] = "delivered"
                _save_outbound()
                return jsonify(success=True)

    return jsonify(success=False, message="Message not found"), 404


# ── WhatsApp contacts endpoint ───────────────────────────────────────────────

@cron_bp.route("/api/whatsapp/contacts")
def api_whatsapp_contacts():
    """Return known WhatsApp contacts from the session map."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    from whatsapp.flask_whatsapp import _session_map

    contacts = []
    for jid, entry in _session_map.items():
        if isinstance(entry, str):
            name = jid.split("@")[0]
        else:
            name = entry.get("sender_name", jid.split("@")[0])
        contacts.append({"jid": jid, "name": name})

    return jsonify(success=True, contacts=contacts)


# ── Module init ──────────────────────────────────────────────────────────────

_load_jobs()
_load_outbound()
logger.info("Cron jobs loaded: %d jobs, %d outbound messages",
            len(_jobs), len(_outbound_queue))

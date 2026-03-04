"""WhatsApp session management blueprint for DREAM-Chat.

Provides Flask-side session management so the Flask backend serves as the
central control (总控) for all WhatsApp conversations.  The Node.js WhatsApp
bridge calls these endpoints instead of the generic /api/new_session +
/api/message combo, and Flask owns the sender_jid → session_id mapping.

Endpoints
---------
POST /api/whatsapp/message   – Bridge sends a message; Flask resolves the
                                session, runs the LLM, and returns the reply.
GET  /api/whatsapp/sessions  – List all WhatsApp sessions with sender metadata.
GET  /api/whatsapp/session/<session_id> – Conversation history for one session.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

whatsapp_bp = Blueprint("whatsapp", __name__)

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "chat_history"
WHATSAPP_USER_DIR = DATA_DIR / "whatsapp_bot"
SESSION_MAP_PATH = WHATSAPP_USER_DIR / "_session_map.json"

# ── Session map (sender_jid → session_id) ────────────────────────────────────

_session_map: dict[str, dict] = {}
_in_flight: set[str] = set()


def _load_session_map() -> None:
    global _session_map
    WHATSAPP_USER_DIR.mkdir(parents=True, exist_ok=True)
    if SESSION_MAP_PATH.exists():
        with open(SESSION_MAP_PATH, "r", encoding="utf-8") as f:
            _session_map = json.load(f)


def _save_session_map() -> None:
    WHATSAPP_USER_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(_session_map, f, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _session_file(session_id: str) -> Path:
    return WHATSAPP_USER_DIR / f"{session_id}.json"


def _load_chat(session_id: str) -> dict:
    p = _session_file(session_id)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_chat(payload: dict) -> None:
    WHATSAPP_USER_DIR.mkdir(parents=True, exist_ok=True)
    p = _session_file(payload["session_id"])
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ── Session management ───────────────────────────────────────────────────────

def _get_or_create_session(sender_jid: str, sender_name: str) -> str:
    """Return the chat session_id for *sender_jid*, creating one if needed."""
    entry = _session_map.get(sender_jid)
    if entry:
        session_id = entry if isinstance(entry, str) else entry.get("session_id", "")
        if session_id and _session_file(session_id).exists():
            # Update sender_name in case it changed
            if isinstance(entry, dict) and entry.get("sender_name") != sender_name:
                entry["sender_name"] = sender_name
                _save_session_map()
            return session_id

    from app import CONFIG, system_prompt

    session_id = uuid.uuid4().hex[:12]
    display_name = sender_name or sender_jid.split("@")[0]
    payload = {
        "session_id": session_id,
        "source": "whatsapp",
        "sender_jid": sender_jid,
        "sender_name": display_name,
        "title": f"WhatsApp: {display_name}",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "conversation": [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": CONFIG["chatbot"]["prologue"]},
        ],
    }
    _save_chat(payload)

    _session_map[sender_jid] = {
        "session_id": session_id,
        "sender_name": display_name,
    }
    _save_session_map()
    logger.info("Created session %s for WhatsApp user %s (%s)",
                session_id, display_name, sender_jid)
    return session_id


# ── Message handling (mirrors app.api_message) ──────────────────────────────

def handle_message(sender_jid: str, sender_name: str, content: str) -> tuple[str, str]:
    """Process one inbound WhatsApp message and return (reply, session_id)."""
    if sender_jid in _in_flight:
        logger.debug("Message from %s already in-flight, dropping", sender_jid)
        return "", ""
    _in_flight.add(sender_jid)

    try:
        session_id = _get_or_create_session(sender_jid, sender_name)
        d = _load_chat(session_id)
        if not d:
            logger.error("Session %s not found on disk", session_id)
            return "Internal error — session lost.", session_id

        d["conversation"].append({"role": "user", "content": content})

        from app import Chatbot, PATIENT_DATA, system_prompt

        messages = d["conversation"].copy()
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                base = system_prompt
                if PATIENT_DATA:
                    base += f"\n\nPatient Information:\n{json.dumps(PATIENT_DATA, indent=2)}"
                messages[i] = {"role": "system", "content": base}
                break

        # Check for reminder intent via LLM
        try:
            from cron_jobs import create_reminder_from_chat
            reminder_job = create_reminder_from_chat(
                user_message=content,
                user="whatsapp_bot",
                sender_jid=sender_jid,
            )
            if reminder_job:
                from datetime import datetime as _dt
                scheduled = _dt.fromisoformat(reminder_job["scheduled_at"])
                time_str = scheduled.strftime("%B %d, %Y at %I:%M %p")
                logger.info("Auto-created WA reminder %s for %s at %s",
                            reminder_job["job_id"], sender_jid, time_str)
                messages.append({
                    "role": "system",
                    "content": (
                        f"[System: a reminder has been successfully created. "
                        f"It will fire on {time_str} and deliver a WhatsApp "
                        f"message about: \"{reminder_job['message']}\". "
                        f"Acknowledge this to the user naturally.]"
                    ),
                })
        except Exception as e:
            logger.error("Reminder parse failed: %s", e, exc_info=True)

        resp = Chatbot.llm_reply(messages)
        reply = resp.content if hasattr(resp, "content") else str(resp)

        d["conversation"].append({"role": "assistant", "content": reply})
        d["updated_at"] = _now_iso()
        _save_chat(d)

        user_msgs = [m for m in d["conversation"] if m.get("role") == "user"]
        asst_msgs = [m for m in d["conversation"] if m.get("role") == "assistant"]
        if len(user_msgs) == 1 and len(asst_msgs) == 2:
            from app import _generate_summary_async
            _generate_summary_async("whatsapp_bot", session_id, d["conversation"])

        logger.info("Reply to WhatsApp user %s (len=%d)", sender_jid, len(reply))
        return reply, session_id
    except Exception as e:
        logger.error(
            "Failed to handle message from %s: %s", sender_jid, e, exc_info=True,
        )
        return (
            "Sorry, I'm having trouble responding right now. "
            "Please try again in a moment."
        ), ""
    finally:
        _in_flight.discard(sender_jid)


# ── Flask endpoints ──────────────────────────────────────────────────────────

def _require_login() -> bool:
    """Re-use the same login check as the main app."""
    from flask import session as flask_session
    from app import USERS
    u = flask_session.get("username")
    return bool(u and u in USERS)


@whatsapp_bp.route("/api/whatsapp/message", methods=["POST"])
def api_whatsapp_message():
    """Bridge calls this to send a user message and receive the AI reply.

    Expects JSON: {sender_jid, sender_name, message}
    Returns JSON:  {success, assistant_message, session_id}
    """
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json(force=True)
    sender_jid = (data.get("sender_jid") or "").strip()
    sender_name = (data.get("sender_name") or "").strip()
    text = (data.get("message") or "").strip()

    if not sender_jid:
        return jsonify(success=False, message="sender_jid is required"), 400
    if not text:
        return jsonify(success=False, message="message is required"), 400

    reply, session_id = handle_message(sender_jid, sender_name, text)

    if not reply:
        return jsonify(success=False, message="Message dropped (in-flight)"), 429

    return jsonify(success=True, assistant_message=reply, session_id=session_id)


@whatsapp_bp.route("/api/whatsapp/sessions")
def api_whatsapp_sessions():
    """List all WhatsApp sessions with sender metadata (总控 dashboard)."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    sessions = []
    for sender_jid, entry in _session_map.items():
        if isinstance(entry, str):
            session_id = entry
            sender_name = sender_jid.split("@")[0]
        else:
            session_id = entry.get("session_id", "")
            sender_name = entry.get("sender_name", sender_jid.split("@")[0])

        d = _load_chat(session_id)
        if not d:
            continue

        msg_count = sum(
            1 for m in d.get("conversation", [])
            if m.get("role") in ("user", "assistant")
        )

        sessions.append({
            "session_id": session_id,
            "sender_jid": sender_jid,
            "sender_name": sender_name,
            "title": d.get("title", f"WhatsApp: {sender_name}"),
            "message_count": msg_count,
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
        })

    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return jsonify(success=True, sessions=sessions)


@whatsapp_bp.route("/api/whatsapp/session/<session_id>")
def api_whatsapp_session(session_id: str):
    """Return conversation history for a specific WhatsApp session."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    d = _load_chat(session_id)
    if not d:
        return jsonify(success=False, message="Session not found"), 404

    convo = [
        {"role": m["role"], "content": m["content"]}
        for m in d.get("conversation", [])
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    return jsonify(
        success=True,
        session_id=session_id,
        sender_jid=d.get("sender_jid", ""),
        sender_name=d.get("sender_name", ""),
        title=d.get("title", ""),
        conversation=convo,
    )


# ── Module init ──────────────────────────────────────────────────────────────

_load_session_map()
logger.info("WhatsApp session manager loaded (%d sessions)", len(_session_map))

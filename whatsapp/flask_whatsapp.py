"""WhatsApp session management blueprint for DREAM-Chat.

Provides Flask-side session management so the Flask backend serves as the
central control (总控) for all WhatsApp conversations.  The Node.js WhatsApp
bridge calls these endpoints instead of the generic /api/new_session +
/api/message combo, and Flask owns the sender_jid → session_id mapping.

Also provides proxy endpoints that forward connection-management requests to
the Node.js WhatsApp service's internal REST API, and a settings page for
users to link/unlink their WhatsApp account.

Endpoints
---------
POST /api/whatsapp/message   – Bridge sends a message; Flask resolves the
                                session, runs the LLM, and returns the reply.
GET  /api/whatsapp/sessions  – List all WhatsApp sessions with sender metadata.
GET  /api/whatsapp/session/<session_id> – Conversation history for one session.
POST /api/whatsapp/connect   – Proxy: start WhatsApp linking for current user.
POST /api/whatsapp/disconnect – Proxy: disconnect current user's WhatsApp.
GET  /api/whatsapp/status    – Proxy: get current user's connection status.
GET  /settings/whatsapp      – Settings page for WhatsApp connection.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import requests as http_requests
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

whatsapp_bp = Blueprint("whatsapp", __name__)

logger = logging.getLogger(__name__)

# ── Node.js WhatsApp service config ──────────────────────────────────────────

NODE_WA_URL = os.environ.get("NODE_WA_URL", "http://localhost:3001")
NODE_API_KEY = os.environ.get("NODE_API_KEY", "")

# ── Paths ────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "chat_history"


def _user_dir(user_id: int) -> Path:
    """Return the chat history directory for a given user_id."""
    return DATA_DIR / f"wa_user_{user_id}"


def _session_map_path(user_id: int) -> Path:
    """Return the path to the session map file for a given user_id."""
    return _user_dir(user_id) / "_session_map.json"


# ── Session map (sender_jid → session_id) ────────────────────────────────────

_in_flight: set[tuple[int, str]] = set()


def _load_session_map(user_id: int) -> dict[str, dict]:
    """Load and return the session map for a specific user_id."""
    udir = _user_dir(user_id)
    udir.mkdir(parents=True, exist_ok=True)
    smap_path = _session_map_path(user_id)
    if smap_path.exists():
        with open(smap_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_session_map(user_id: int, session_map: dict[str, dict]) -> None:
    """Persist the session map for a specific user_id."""
    udir = _user_dir(user_id)
    udir.mkdir(parents=True, exist_ok=True)
    smap_path = _session_map_path(user_id)
    with open(smap_path, "w", encoding="utf-8") as f:
        json.dump(session_map, f, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _session_file(user_id: int, session_id: str) -> Path:
    return _user_dir(user_id) / f"{session_id}.json"


def _load_chat(user_id: int, session_id: str) -> dict:
    p = _session_file(user_id, session_id)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_chat(user_id: int, payload: dict) -> None:
    udir = _user_dir(user_id)
    udir.mkdir(parents=True, exist_ok=True)
    p = _session_file(user_id, payload["session_id"])
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ── Session management ───────────────────────────────────────────────────────

def _get_or_create_session(user_id: int, sender_jid: str, sender_name: str) -> str:
    """Return the chat session_id for *sender_jid*, creating one if needed."""
    session_map = _load_session_map(user_id)
    entry = session_map.get(sender_jid)
    if entry:
        session_id = entry if isinstance(entry, str) else entry.get("session_id", "")
        if session_id and _session_file(user_id, session_id).exists():
            # Update sender_name in case it changed
            if isinstance(entry, dict) and entry.get("sender_name") != sender_name:
                entry["sender_name"] = sender_name
                _save_session_map(user_id, session_map)
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
    _save_chat(user_id, payload)

    session_map[sender_jid] = {
        "session_id": session_id,
        "sender_name": display_name,
    }
    _save_session_map(user_id, session_map)
    logger.info("Created session %s for WhatsApp user %s (%s)",
                session_id, display_name, sender_jid)
    return session_id


# ── Message handling (mirrors app.api_message) ──────────────────────────────

def handle_message(
    user_id: int,
    sender_jid: str,
    sender_name: str,
    content: str,
    images: list[str] | None = None,
) -> tuple[str, str, list]:
    """Process one inbound WhatsApp message and return (reply, session_id, exercise_images)."""
    flight_key = (user_id, sender_jid)
    if flight_key in _in_flight:
        logger.debug("Message from %s (user %d) already in-flight, dropping", sender_jid, user_id)
        return "", "", []
    _in_flight.add(flight_key)

    user_dir_name = f"wa_user_{user_id}"

    try:
        session_id = _get_or_create_session(user_id, sender_jid, sender_name)
        d = _load_chat(user_id, session_id)
        if not d:
            logger.error("Session %s not found on disk", session_id)
            return "Internal error — session lost.", session_id, []

        user_msg: dict = {"role": "user", "content": content}
        if images:
            user_msg["images"] = images
        d["conversation"].append(user_msg)

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
            from functions.cron_jobs import create_reminder_from_chat
            reminder_job = create_reminder_from_chat(
                user_message=content,
                user=user_dir_name,
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
        exercise_images = getattr(resp, "exercise_images", []) or []

        assistant_entry = {"role": "assistant", "content": reply}
        if exercise_images:
            assistant_entry["exercise_images"] = exercise_images
        d["conversation"].append(assistant_entry)
        d["updated_at"] = _now_iso()
        _save_chat(user_id, d)

        user_msgs = [m for m in d["conversation"] if m.get("role") == "user"]
        asst_msgs = [m for m in d["conversation"] if m.get("role") == "assistant"]
        if len(user_msgs) == 1 and len(asst_msgs) == 2:
            from app import _generate_summary_async
            _generate_summary_async(user_dir_name, session_id, d["conversation"])

        logger.info("Reply to WhatsApp user %s (len=%d)", sender_jid, len(reply))
        return reply, session_id, exercise_images
    except Exception as e:
        logger.error(
            "Failed to handle message from %s: %s", sender_jid, e, exc_info=True,
        )
        return (
            "Sorry, I'm having trouble responding right now. "
            "Please try again in a moment."
        ), "", []
    finally:
        _in_flight.discard(flight_key)


# ── Flask endpoints ──────────────────────────────────────────────────────────

def _require_login() -> bool:
    """Re-use the same login check as the main app."""
    return current_user.is_authenticated


@whatsapp_bp.route("/api/whatsapp/message", methods=["POST"])
def api_whatsapp_message():
    """Bridge calls this to send a user message and receive the AI reply.

    Expects JSON: {sender_jid, sender_name, message, user_id}
    Returns JSON:  {success, assistant_message, session_id}
    """
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json(force=True)
    sender_jid = (data.get("sender_jid") or "").strip()
    sender_name = (data.get("sender_name") or "").strip()
    text = (data.get("message") or "").strip()
    images = data.get("images") or []
    raw_user_id = data.get("user_id")

    if not sender_jid:
        return jsonify(success=False, message="sender_jid is required"), 400
    if not text and not images:
        return jsonify(success=False, message="message is required"), 400

    # Validate user_id as an integer
    if raw_user_id is None:
        return jsonify(success=False, message="user_id is required"), 400
    try:
        user_id = int(raw_user_id)
    except (ValueError, TypeError):
        return jsonify(success=False, message="user_id must be an integer"), 400

    reply, session_id, exercise_images = handle_message(user_id, sender_jid, sender_name, text, images or None)

    if not reply:
        return jsonify(success=False, message="Message dropped (in-flight)"), 429

    result = {"success": True, "assistant_message": reply, "session_id": session_id}
    if exercise_images:
        result["exercise_images"] = exercise_images
    return jsonify(result)


@whatsapp_bp.route("/api/whatsapp/sessions")
def api_whatsapp_sessions():
    """List all WhatsApp sessions with sender metadata (总控 dashboard).

    Requires query param ?user_id=<int> to specify which user's sessions to list.
    """
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    raw_user_id = request.args.get("user_id")
    if raw_user_id is None:
        return jsonify(success=False, message="user_id query param is required"), 400
    try:
        user_id = int(raw_user_id)
    except (ValueError, TypeError):
        return jsonify(success=False, message="user_id must be an integer"), 400

    session_map = _load_session_map(user_id)
    sessions = []
    for sender_jid, entry in session_map.items():
        if isinstance(entry, str):
            session_id = entry
            sender_name = sender_jid.split("@")[0]
        else:
            session_id = entry.get("session_id", "")
            sender_name = entry.get("sender_name", sender_jid.split("@")[0])

        d = _load_chat(user_id, session_id)
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
    """Return conversation history for a specific WhatsApp session.

    Requires query param ?user_id=<int>.
    """
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    raw_user_id = request.args.get("user_id")
    if raw_user_id is None:
        return jsonify(success=False, message="user_id query param is required"), 400
    try:
        user_id = int(raw_user_id)
    except (ValueError, TypeError):
        return jsonify(success=False, message="user_id must be an integer"), 400

    d = _load_chat(user_id, session_id)
    if not d:
        return jsonify(success=False, message="Session not found"), 404

    convo = []
    for m in d.get("conversation", []):
        if m.get("role") in ("user", "assistant") and (m.get("content") or m.get("images")):
            entry = {"role": m["role"], "content": m.get("content", "")}
            if m.get("images"):
                entry["images"] = m["images"]
            convo.append(entry)

    return jsonify(
        success=True,
        session_id=session_id,
        sender_jid=d.get("sender_jid", ""),
        sender_name=d.get("sender_name", ""),
        title=d.get("title", ""),
        conversation=convo,
    )


# ── Node.js proxy helpers ────────────────────────────────────────────────────

def _node_headers() -> dict:
    """Build headers for requests to the Node.js WhatsApp API."""
    headers = {"Content-Type": "application/json"}
    if NODE_API_KEY:
        headers["X-Api-Key"] = NODE_API_KEY
    return headers


def _node_request(method: str, path: str, **kwargs) -> dict | None:
    """Make a request to the Node.js WhatsApp API. Returns parsed JSON or None."""
    url = f"{NODE_WA_URL}{path}"
    try:
        resp = http_requests.request(
            method, url, headers=_node_headers(), timeout=10, **kwargs
        )
        return resp.json()
    except http_requests.ConnectionError:
        return None
    except Exception as e:
        logger.error("Node.js API request failed: %s %s — %s", method, path, e)
        return None


# ── Connection management proxy endpoints ────────────────────────────────────

@whatsapp_bp.route("/api/whatsapp/connect", methods=["POST"])
@login_required
def api_whatsapp_connect():
    """Start WhatsApp linking for the logged-in user."""
    user_id = current_user.id
    result = _node_request("POST", f"/api/connections/{user_id}/connect")
    if result is None:
        return jsonify(success=False, message="WhatsApp service unavailable"), 502
    status_code = 200 if result.get("success") else 409
    return jsonify(result), status_code


@whatsapp_bp.route("/api/whatsapp/disconnect", methods=["POST"])
@login_required
def api_whatsapp_disconnect():
    """Disconnect the logged-in user's WhatsApp."""
    user_id = current_user.id
    result = _node_request("POST", f"/api/connections/{user_id}/disconnect")
    if result is None:
        return jsonify(success=False, message="WhatsApp service unavailable"), 502
    status_code = 200 if result.get("success") else 404
    return jsonify(result), status_code


@whatsapp_bp.route("/api/whatsapp/status")
@login_required
def api_whatsapp_status():
    """Get WhatsApp connection status for the logged-in user."""
    user_id = current_user.id
    result = _node_request("GET", f"/api/connections/{user_id}/status")
    if result is None:
        return jsonify(
            success=True,
            status="disconnected",
            phone_number=None,
            qr_data_url=None,
            warning="WhatsApp service unavailable",
        )
    return jsonify(
        success=result.get("success", True),
        status=result.get("status", "disconnected"),
        phone_number=result.get("phoneNumber"),
        qr_data_url=result.get("qrDataUrl"),
    )


# ── Settings page ────────────────────────────────────────────────────────────

def _username():
    """Get the current user's email for template context."""
    if current_user.is_authenticated:
        return current_user.email
    return None


@whatsapp_bp.route("/settings/whatsapp")
@login_required
def settings_whatsapp_page():
    """Render the WhatsApp settings page."""
    return render_template(
        "settings_whatsapp.html",
        username=_username(),
        settings_section="whatsapp",
    )


# ── Public helpers for other modules ─────────────────────────────────────────

def load_session_map_for_user(user_id: int) -> dict[str, dict]:
    """Load the session map for a specific user (used by cron_jobs contacts endpoint)."""
    return _load_session_map(user_id)


logger.info("WhatsApp session manager loaded")

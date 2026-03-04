"""WeChat Official Account integration blueprint for DREAM-Chat.

Provides webhook endpoints for the WeChat Official Account platform,
allowing users to chat with the AI bot directly inside WeChat.

The Flask backend manages all WeChat conversations centrally, mirroring
the WhatsApp integration pattern (openid → session_id mapping).

WeChat imposes a 5-second response timeout on passive replies.  To avoid
this, incoming messages are acknowledged immediately with ``"success"``
and the bot reply is delivered asynchronously via the Customer Service
Message API.

Endpoints
---------
GET/POST /api/wechat/webhook           – WeChat server verification & message intake.
GET      /api/wechat/sessions          – List all WeChat chat sessions.
GET      /api/wechat/session/<sid>     – Conversation history for one session.
"""

import base64
import hashlib
import json
import logging
import os
import struct
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests as http_requests
from flask import Blueprint, Response, jsonify
from flask import request as flask_request

wechat_bp = Blueprint("wechat_official", __name__)
logger = logging.getLogger(__name__)

# ── Configuration (from environment) ─────────────────────────────────────────

WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "")
WECHAT_TOKEN = os.environ.get("WECHAT_TOKEN", "")
WECHAT_ENCODING_AES_KEY = os.environ.get("WECHAT_ENCODING_AES_KEY", "")
# "plain", "compatible", or "safe"
WECHAT_ENCRYPTION_MODE = os.environ.get("WECHAT_ENCRYPTION_MODE", "plain")

# ── Paths ────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "chat_history"
WECHAT_USER_DIR = DATA_DIR / "wechat_bot"
SESSION_MAP_PATH = WECHAT_USER_DIR / "_session_map.json"

# ── Session map (openid → session metadata) ──────────────────────────────────

_session_map: dict[str, dict] = {}
_in_flight: set[str] = set()

# Dedup recent MsgIds to handle WeChat retries (keeps last 200)
_recent_msg_ids: list[str] = []
_MSG_ID_CACHE_SIZE = 200


def _load_session_map() -> None:
    global _session_map
    WECHAT_USER_DIR.mkdir(parents=True, exist_ok=True)
    if SESSION_MAP_PATH.exists():
        with open(SESSION_MAP_PATH, "r", encoding="utf-8") as f:
            _session_map = json.load(f)


def _save_session_map() -> None:
    WECHAT_USER_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(_session_map, f, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _session_file(session_id: str) -> Path:
    return WECHAT_USER_DIR / f"{session_id}.json"


def _load_chat(session_id: str) -> dict:
    p = _session_file(session_id)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_chat(payload: dict) -> None:
    WECHAT_USER_DIR.mkdir(parents=True, exist_ok=True)
    p = _session_file(payload["session_id"])
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ── Access-token management ──────────────────────────────────────────────────

_access_token: str = ""
_token_expires_at: float = 0


def _get_access_token() -> str:
    """Return a valid WeChat API access token, refreshing when needed."""
    global _access_token, _token_expires_at

    if _access_token and time.time() < _token_expires_at - 300:
        return _access_token

    if not WECHAT_APP_ID or not WECHAT_APP_SECRET:
        logger.error("WECHAT_APP_ID or WECHAT_APP_SECRET not configured")
        return ""

    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": WECHAT_APP_ID,
        "secret": WECHAT_APP_SECRET,
    }

    try:
        resp = http_requests.get(url, params=params, timeout=10)
        data = resp.json()

        if "access_token" in data:
            _access_token = data["access_token"]
            _token_expires_at = time.time() + data.get("expires_in", 7200)
            logger.info("WeChat access token refreshed (expires in %ds)",
                        data.get("expires_in", 7200))
            return _access_token

        logger.error("Failed to get WeChat access token: %s", data)
        return ""
    except Exception as e:
        logger.error("Error fetching WeChat access token: %s", e)
        return ""


def _send_customer_service_message(openid: str, text: str) -> bool:
    """Send a text reply via the Customer Service Message API."""
    token = _get_access_token()
    if not token:
        logger.error("Cannot send WeChat message: no access token")
        return False

    url = (
        "https://api.weixin.qq.com/cgi-bin/message/custom/send"
        f"?access_token={token}"
    )
    payload = {
        "touser": openid,
        "msgtype": "text",
        "text": {"content": text},
    }

    try:
        resp = http_requests.post(url, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode", 0) == 0:
            logger.info("Sent customer-service message to %s", openid)
            return True

        logger.error("WeChat send failed: %s", data)
        return False
    except Exception as e:
        logger.error("Error sending WeChat message: %s", e)
        return False


# ── Session management ───────────────────────────────────────────────────────

def _get_or_create_session(openid: str) -> str:
    """Return the chat session_id for *openid*, creating one if needed."""
    entry = _session_map.get(openid)
    if entry:
        session_id = entry if isinstance(entry, str) else entry.get("session_id", "")
        if session_id and _session_file(session_id).exists():
            return session_id

    from app import CONFIG, system_prompt

    session_id = uuid.uuid4().hex[:12]
    display_name = f"WeChat:{openid[:8]}"
    payload = {
        "session_id": session_id,
        "source": "wechat",
        "openid": openid,
        "title": f"WeChat: {display_name}",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "conversation": [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": CONFIG["chatbot"]["prologue"]},
        ],
    }
    _save_chat(payload)

    _session_map[openid] = {"session_id": session_id}
    _save_session_map()
    logger.info("Created WeChat session %s for user %s", session_id, openid)
    return session_id


# ── Asynchronous message handling ────────────────────────────────────────────

def _handle_message_async(openid: str, content: str) -> None:
    """Spawn a background thread to process the message and reply via API."""
    if openid in _in_flight:
        logger.debug("WeChat message from %s already in-flight, dropping", openid)
        return
    _in_flight.add(openid)

    def _process():
        try:
            session_id = _get_or_create_session(openid)
            d = _load_chat(session_id)
            if not d:
                logger.error("WeChat session %s missing on disk", session_id)
                _send_customer_service_message(
                    openid, "Internal error — please try again.")
                return

            d["conversation"].append({"role": "user", "content": content})

            from app import Chatbot, PATIENT_DATA

            messages = d["conversation"].copy()
            if PATIENT_DATA:
                for i, msg in enumerate(messages):
                    if msg.get("role") == "system":
                        patient_info = (
                            f"\n\nPatient Information:\n"
                            f"{json.dumps(PATIENT_DATA, indent=2)}"
                        )
                        messages[i] = {
                            "role": "system",
                            "content": msg["content"] + patient_info,
                        }
                        break

            resp = Chatbot.llm_reply(messages)
            reply = resp.content if hasattr(resp, "content") else str(resp)

            d["conversation"].append({"role": "assistant", "content": reply})
            d["updated_at"] = _now_iso()
            _save_chat(d)

            user_msgs = [m for m in d["conversation"] if m.get("role") == "user"]
            asst_msgs = [m for m in d["conversation"] if m.get("role") == "assistant"]
            if len(user_msgs) == 1 and len(asst_msgs) == 2:
                from app import _generate_summary_async
                _generate_summary_async("wechat_bot", session_id, d["conversation"])

            _send_customer_service_message(openid, reply)
            logger.info("Reply sent to WeChat user %s (len=%d)", openid, len(reply))

        except Exception as e:
            logger.error("Failed to handle WeChat message from %s: %s",
                         openid, e, exc_info=True)
            _send_customer_service_message(
                openid,
                "Sorry, I'm having trouble responding right now. "
                "Please try again in a moment.",
            )
        finally:
            _in_flight.discard(openid)

    thread = threading.Thread(target=_process, daemon=True)
    thread.start()


# ── WeChat signature verification ────────────────────────────────────────────

def _check_signature(signature: str, timestamp: str, nonce: str) -> bool:
    """Verify that a request genuinely comes from WeChat servers."""
    if not WECHAT_TOKEN:
        logger.warning("WECHAT_TOKEN not configured — skipping signature check")
        return True

    items = sorted([WECHAT_TOKEN, timestamp, nonce])
    computed = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
    return computed == signature


# ── XML helpers ──────────────────────────────────────────────────────────────

def _parse_xml(xml_bytes: bytes) -> dict:
    """Parse a WeChat XML message body into a flat dict."""
    root = ET.fromstring(xml_bytes)
    return {child.tag: (child.text or "") for child in root}


# ── Safe-mode decryption ─────────────────────────────────────────────────────

def _decrypt_message(encrypt_str: str) -> str:
    """Decrypt an AES-CBC encrypted WeChat message (safe / compatible mode).

    The EncodingAESKey (43 chars) is base64-decoded to a 32-byte AES key.
    The IV is the first 16 bytes of the key.  The plaintext layout is:

        16-byte random | 4-byte msg-length (big-endian) | message | app_id
    """
    key = base64.b64decode(WECHAT_ENCODING_AES_KEY + "=")
    iv = key[:16]

    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(base64.b64decode(encrypt_str))

    # PKCS#7 unpadding
    pad_len = decrypted[-1]
    decrypted = decrypted[:-pad_len]

    msg_len = struct.unpack("!I", decrypted[16:20])[0]
    message = decrypted[20:20 + msg_len].decode("utf-8")
    return message


def _extract_message_xml(raw_body: bytes) -> bytes:
    """Return the inner message XML, decrypting if in safe/compatible mode."""
    if WECHAT_ENCRYPTION_MODE in ("safe", "compatible"):
        outer = _parse_xml(raw_body)
        encrypt_str = outer.get("Encrypt", "")
        if encrypt_str:
            return _decrypt_message(encrypt_str).encode("utf-8")
    return raw_body


# ── Flask endpoints ──────────────────────────────────────────────────────────

@wechat_bp.route("/api/wechat/webhook", methods=["GET", "POST"])
def wechat_webhook():
    """WeChat webhook: GET = server verification, POST = incoming message."""

    signature = flask_request.args.get("signature", "")
    timestamp = flask_request.args.get("timestamp", "")
    nonce = flask_request.args.get("nonce", "")

    if flask_request.method == "GET":
        echostr = flask_request.args.get("echostr", "")
        if _check_signature(signature, timestamp, nonce):
            logger.info("WeChat server URL verification succeeded")
            return Response(echostr, content_type="text/plain")
        logger.warning("WeChat server URL verification failed")
        return Response("Verification failed", status=403)

    # POST — incoming message
    if not _check_signature(signature, timestamp, nonce):
        logger.warning("Invalid signature on incoming WeChat message")
        return Response("Invalid signature", status=403)

    try:
        inner_xml = _extract_message_xml(flask_request.data)
        msg = _parse_xml(inner_xml)
    except Exception as e:
        logger.error("Failed to parse WeChat message: %s", e, exc_info=True)
        return Response("success", content_type="text/plain")

    msg_type = msg.get("MsgType", "")
    from_user = msg.get("FromUserName", "")  # openid
    content = msg.get("Content", "").strip()
    msg_id = msg.get("MsgId", "")

    # Dedup retried messages from WeChat
    if msg_id and msg_id in _recent_msg_ids:
        logger.debug("Duplicate MsgId %s, ignoring", msg_id)
        return Response("success", content_type="text/plain")
    if msg_id:
        _recent_msg_ids.append(msg_id)
        if len(_recent_msg_ids) > _MSG_ID_CACHE_SIZE:
            del _recent_msg_ids[:len(_recent_msg_ids) - _MSG_ID_CACHE_SIZE]

    logger.info("WeChat %s message from %s: %s",
                msg_type, from_user, content[:80] if content else "(empty)")

    if msg_type == "text" and content and from_user:
        _handle_message_async(from_user, content)

    elif msg_type == "event":
        event = msg.get("Event", "")
        if event == "subscribe" and from_user:
            logger.info("New WeChat subscriber: %s", from_user)
            try:
                from app import CONFIG
                welcome = CONFIG.get("chatbot", {}).get(
                    "prologue", "Welcome! How can I help you?")
                _send_customer_service_message(from_user, welcome)
            except Exception as e:
                logger.error("Failed to send welcome message: %s", e)

    return Response("success", content_type="text/plain")


# ── Admin / dashboard endpoints (require Flask login) ────────────────────────

def _require_login() -> bool:
    from flask import session as flask_session
    from app import USERS
    u = flask_session.get("username")
    return bool(u and u in USERS)


@wechat_bp.route("/api/wechat/sessions")
def api_wechat_sessions():
    """List all WeChat chat sessions."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    sessions = []
    for openid, entry in _session_map.items():
        session_id = entry if isinstance(entry, str) else entry.get("session_id", "")
        d = _load_chat(session_id)
        if not d:
            continue

        msg_count = sum(
            1 for m in d.get("conversation", [])
            if m.get("role") in ("user", "assistant")
        )
        sessions.append({
            "session_id": session_id,
            "openid": openid,
            "title": d.get("title", f"WeChat: {openid[:8]}"),
            "message_count": msg_count,
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
        })

    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return jsonify(success=True, sessions=sessions)


@wechat_bp.route("/api/wechat/session/<session_id>")
def api_wechat_session(session_id: str):
    """Return conversation history for one WeChat session."""
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
        openid=d.get("openid", ""),
        title=d.get("title", ""),
        conversation=convo,
    )


# ── Module init ──────────────────────────────────────────────────────────────

_load_session_map()
logger.info("WeChat Official Account manager loaded (%d sessions)",
            len(_session_map))

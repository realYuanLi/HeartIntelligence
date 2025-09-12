import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

# --------------------------------------------------------------------------------
# Attempt to import the user's Agent class (from functions/agent.py)
# If unavailable, fall back to a minimal dummy Agent so the app still runs.
# --------------------------------------------------------------------------------
try:
    import sys
    # sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from functions.agent import Agent
except Exception as e:
    class _Resp:
        def __init__(self, content: str):
            self.content = content
    class Agent:
        def __init__(self, role: str, llm: str, temperature: float, sys_message: str):
            self.role = role
            self.llm = llm
            self.temperature = temperature
            self.sys_message = sys_message
        def llm_reply(self, messages: list[dict]):
            last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            return _Resp(f"(dummy {self.llm}) You said: {last_user}")

# --------------------------------------------------------------------------------
# Paths & config
# --------------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config" / "configs.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

Chatbot = Agent(
    role="DREAM assistant",
    llm=CONFIG["chatbot"]["llm_model"],
    temperature=0.7,
    sys_message=CONFIG["chatbot"]["system_prompt"]
)

# --------------------------------------------------------------------------------
# Flask setup
# --------------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "replace-with-your-secret")

# ---- 写死的账号密码 ----
USERS = {"Kevin": "123456", "Fang": "123456"}

def _username() -> str | None:
    return session.get("username")

def _require_login() -> bool:
    u = session.get("username")
    if not u or u not in USERS:
        return False
    return True

def _user_dir(user: str) -> Path:
    d = DATA_DIR / user
    d.mkdir(parents=True, exist_ok=True)
    return d

def _session_path(user: str, session_id: str) -> Path:
    return _user_dir(user) / f"{session_id}.json"

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _load_session(user: str, session_id: str) -> dict:
    p = _session_path(user, session_id)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_session(user: str, payload: dict):
    p = _session_path(user, payload["session_id"])
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

# --------------------------------------------------------------------------------
# Routes (pages)
# --------------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("new_chat"))

@app.route("/new-chat")
def new_chat():
    return render_template("new_chat.html", username=session.get("username"))

@app.route("/chat/<session_id>")
def chat(session_id: str):
    return render_template("chat.html", username=session.get("username"))

# --------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    u = (data.get("username") or "").strip()
    p = (data.get("password") or "").strip()

    if u not in USERS:
        return jsonify(success=False, message="User not found."), 401
    if USERS[u] != p:
        return jsonify(success=False, message="Incorrect password."), 401

    session["username"] = u
    return jsonify(success=True, username=u)

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("username", None)
    return jsonify(success=True)

# --------------------------------------------------------------------------------
# Conversations (login required)
# --------------------------------------------------------------------------------
@app.route("/api/history")
def api_history():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    items = []
    for fn in sorted(_user_dir(user).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with fn.open("r", encoding="utf-8") as f:
                d = json.load(f)
            sid = d.get("session_id", fn.stem)
            # 使用存储的 title；如果缺失，再给一个宽松兜底（不会强制固定为 "DREAM chat + session_id"）
            title = d.get("title") or f"DREAM chat {sid}"
            items.append({
                "session_id": sid,
                "title": title,
                "updated_at": d.get("updated_at") or datetime.fromtimestamp(fn.stat().st_mtime).isoformat(timespec="seconds")
            })
        except Exception:
            continue
    return jsonify(items)

@app.route("/api/new_session", methods=["POST"])
def api_new_session():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    session_id = uuid.uuid4().hex[:12]
    greeting = "Hello, how are you today?"
    payload = {
        "session_id": session_id,
        # 初始标题可自定义；这里给一个默认值，之后可通过 /api/rename_session 重命名
        "title": f"DREAM chat {session_id}",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "conversation": [
            {"role": "system", "content": Chatbot.sys_message},
            {"role": "assistant", "content": greeting}
        ]
    }
    _save_session(user, payload)
    return jsonify(success=True, session_id=session_id)

@app.route("/api/session/<session_id>")
def api_get_session(session_id: str):
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    d = _load_session(user, session_id)
    if not d:
        return jsonify(success=False, message="Session not found"), 404
    # Hide system messages; chat starts from the assistant greeting
    convo = [
        {"role": m.get("role"), "content": m.get("content","")}
        for m in d.get("conversation", [])
        if m.get("role") in {"user", "assistant", "assistant-error"} and m.get("content")
    ]
    return jsonify(success=True, conversation=convo)

@app.route("/api/message", methods=["POST"])
def api_message():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify(success=False, assistant_message="Please type a message."), 400

    d = _load_session(user, session_id)
    if not d:
        return jsonify(success=False, assistant_message="Session not found."), 404

    d["conversation"].append({"role": "user", "content": text})
    messages = d["conversation"]

    try:
        resp = Chatbot.llm_reply(messages)
        assistant_text = resp.content if hasattr(resp, "content") else str(resp)
        d["conversation"].append({"role": "assistant", "content": assistant_text})
        d["updated_at"] = _now_iso()
        _save_session(user, d)
        return jsonify(success=True, assistant_message=assistant_text)
    except Exception as e:
        err = f"Error from model: {e}"
        d["conversation"].append({"role": "assistant-error", "content": err})
        d["updated_at"] = _now_iso()
        _save_session(user, d)
        return jsonify(success=False, assistant_message=err), 500

@app.route("/api/rename_session", methods=["POST"])
def api_rename_session():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    new_title = (data.get("new_title") or "").strip()
    if not new_title:
        return jsonify(success=False, message="Title cannot be empty.")

    d = _load_session(user, session_id)
    if not d:
        return jsonify(success=False, message="Session not found"), 404
    d["title"] = new_title
    d["updated_at"] = _now_iso()
    _save_session(user, d)
    return jsonify(success=True)

@app.route("/api/delete_session", methods=["POST"])
def api_delete_session():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    p = _session_path(user, session_id)
    if p.exists():
        p.unlink()
        return jsonify(success=True)
    return jsonify(success=False, message="Session not found"), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)

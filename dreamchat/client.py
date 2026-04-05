"""HTTP client wrapping the DREAM-Chat Flask API.

Handles authentication, session cookie caching, and auto-reauth on 401.
Config and session state live under ~/.dreamchat/.
"""

from __future__ import annotations


class DreamChatError(Exception):
    """Raised on auth failures or unrecoverable client errors."""

import base64
import json
import os
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, build_opener, HTTPCookieProcessor

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".dreamchat"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.txt"
SESSION_FILE = CONFIG_DIR / "session.json"  # stores chat session_id


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Restrict permissions on config dir (contains credentials)
    os.chmod(CONFIG_DIR, 0o700)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load ~/.dreamchat/config.json or return defaults."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(cfg: dict) -> None:
    _ensure_dir()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
    os.chmod(CONFIG_FILE, 0o600)


def load_session_state() -> dict:
    """Load persistent session state (chat session_id, etc.)."""
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return {}


def save_session_state(state: dict) -> None:
    _ensure_dir()
    SESSION_FILE.write_text(json.dumps(state, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DreamChatClient:
    """Thin HTTP client for the DREAM-Chat Flask API."""

    def __init__(self, base_url: str | None = None,
                 email: str | None = None, password: str | None = None,
                 source: str | None = None):
        cfg = load_config()
        self.base_url = (base_url or cfg.get("base_url")
                         or os.environ.get("DREAMCHAT_URL")
                         or "http://localhost:8000")
        self.email = (email or cfg.get("email")
                      or os.environ.get("DREAMCHAT_EMAIL", ""))
        self.password = (password or cfg.get("password")
                         or os.environ.get("DREAMCHAT_PASSWORD", ""))
        self.source = source

        # Cookie-based auth via stdlib (no requests dependency)
        _ensure_dir()
        self._jar = MozillaCookieJar(str(COOKIE_FILE))
        if COOKIE_FILE.exists():
            try:
                self._jar.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        self._opener = build_opener(HTTPCookieProcessor(self._jar))

    # -- low-level --------------------------------------------------------

    def _request(self, method: str, path: str,
                 body: dict | None = None, retry_auth: bool = True) -> dict:
        url = self._url(path)
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")

        try:
            resp = self._opener.open(req, timeout=120)
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if exc.code == 401 and retry_auth:
                self._login()
                return self._request(method, path, body, retry_auth=False)
            raw = exc.read().decode()
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return {"success": False, "message": f"HTTP {exc.code}: {raw[:200]}"}
        except URLError as exc:
            return {"success": False, "message": f"Connection error: {exc.reason}"}

    def _get(self, path: str) -> dict:
        return self._request("GET", path)

    def _post(self, path: str, body: dict | None = None) -> dict:
        return self._request("POST", path, body or {})

    def _url(self, path: str) -> str:
        """Build full URL, handling sub-path deployments correctly."""
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _login(self) -> None:
        """Authenticate and persist cookies."""
        if not self.email or not self.password:
            raise DreamChatError(
                "No credentials configured. Run: dreamchat configure"
            )
        url = self._url("/api/login")
        data = json.dumps({"email": self.email, "password": self.password}).encode()
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            resp = self._opener.open(req, timeout=30)
            result = json.loads(resp.read().decode())
            if not result.get("success"):
                raise DreamChatError(f"Login failed: {result.get('message', 'unknown')}")
            self._jar.save(ignore_discard=True, ignore_expires=True)
            os.chmod(COOKIE_FILE, 0o600)
        except HTTPError as exc:
            raw = exc.read().decode()
            raise DreamChatError(f"Login failed (HTTP {exc.code}): {raw[:200]}")
        except URLError as exc:
            raise DreamChatError(f"Cannot reach server: {exc.reason}")

    # -- public API --------------------------------------------------------

    def server_status(self) -> dict:
        """GET /health -- no auth needed."""
        url = self._url("/health")
        req = Request(url, method="GET")
        try:
            resp = self._opener.open(req, timeout=10)
            raw = resp.read().decode()
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {"status": "unknown", "error": f"Non-JSON response: {raw[:200]}"}
        except (HTTPError, URLError) as exc:
            return {"status": "unreachable", "error": str(exc)}

    def health_data(self) -> dict:
        """GET /api/mobile_health_data."""
        return self._get("/api/mobile_health_data")

    def patient_info(self) -> dict:
        """GET /api/patient_info."""
        return self._get("/api/patient_info")

    def cron_jobs(self) -> dict:
        """GET /api/cron-jobs."""
        return self._get("/api/cron-jobs")

    def heartbeat_status(self) -> dict:
        """GET /api/heartbeat/status."""
        return self._get("/api/heartbeat/status")

    def new_session(self, source: str | None = None) -> dict:
        """POST /api/new_session."""
        body = {"source": source} if source else {}
        return self._post("/api/new_session", body or None)

    def get_session(self, session_id: str) -> dict:
        """GET /api/session/<session_id>."""
        return self._get(f"/api/session/{session_id}")

    def send_message(self, session_id: str, message: str,
                     images: list[str] | None = None) -> dict:
        """POST /api/message."""
        body: dict = {"session_id": session_id, "message": message}
        if images:
            body["images"] = images
        return self._request("POST", "/api/message", body)

    # -- session management ------------------------------------------------

    def ensure_session(self) -> str:
        """Get or create a persistent chat session for CLI use."""
        state = load_session_state()
        sid = state.get("session_id")
        if sid:
            # Verify it still exists
            resp = self.get_session(sid)
            if resp.get("success"):
                return sid
        # Create new session
        resp = self.new_session(source=self.source)
        if not resp.get("success"):
            raise SystemExit(f"Cannot create session: {resp}")
        sid = resp["session_id"]
        state["session_id"] = sid
        save_session_state(state)
        return sid

    def reset_session(self) -> str:
        """Force-create a new chat session."""
        resp = self.new_session(source=self.source)
        if not resp.get("success"):
            raise SystemExit(f"Cannot create session: {resp}")
        sid = resp["session_id"]
        save_session_state({"session_id": sid})
        return sid

    def chat(self, message: str, image_path: str | None = None,
             image_data_uri: str | None = None) -> dict:
        """Send a message in the persistent session, return response.

        Images can be provided as either:
        - image_path: local file path (read and base64-encoded)
        - image_data_uri: pre-encoded data URI (data:image/...;base64,...)
        """
        sid = self.ensure_session()
        images = None
        if image_data_uri:
            images = [image_data_uri]
        elif image_path:
            path = Path(image_path).expanduser()
            if not path.exists():
                return {"success": False, "message": f"Image not found: {path}"}
            raw = path.read_bytes()
            ext = path.suffix.lower().lstrip(".")
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                    "gif": "gif", "webp": "webp"}.get(ext, "jpeg")
            data_uri = f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"
            images = [data_uri]
        return self.send_message(sid, message, images)

"""User Memory module for DREAM-Chat.

Provides persistent per-user memory with short-term (auto-expiring, FIFO-pruned)
and long-term (permanent) layers. Exposes a Flask blueprint with CRUD endpoints
and a UserMemory class for programmatic access.
"""

import json
import math
import re
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify, session, render_template, redirect
from flask_login import current_user, login_required

# ── Constants ────────────────────────────────────────────────────────────────

MAX_PER_CATEGORY = 20
DEFAULT_SHORT_TERM_TTL = 604800  # 7 days in seconds
_HALF_LIFE_DAYS = 30
_LN2 = math.log(2)

SHORT_TERM_CATEGORIES = ["recent_conversations", "recent_plans", "health_status"]
LONG_TERM_CATEGORIES = ["preference", "fact", "saved", "goal"]
PROMOTION_THRESHOLD = 3
_OLD_SHORT_TERM_CATEGORIES = ["page_visits", "chat_topics", "recent_searches", "last_used_skills"]

MEMORY_DIR = Path(__file__).resolve().parent.parent / "personal_data" / "memory"

# ── Per-user locks ───────────────────────────────────────────────────────────

_user_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_lock(username: str) -> threading.Lock:
    with _locks_lock:
        if username not in _user_locks:
            _user_locks[username] = threading.Lock()
        return _user_locks[username]


def _backfill_entry(entry: dict) -> dict:
    """Ensure new fields exist on legacy long-term entries."""
    entry.setdefault("context", None)
    entry.setdefault("evergreen", False)
    entry.setdefault("access_count", 0)
    return entry


def _relevance_score(entry: dict, now: float) -> float:
    """Score a long-term entry for ranking: temporal decay + access boost + evergreen."""
    age_days = max(0, (now - entry.get("ts", now)) / 86400)
    decay = math.exp(-_LN2 * age_days / _HALF_LIFE_DAYS)
    if entry.get("evergreen", False):
        decay = 1.0
    access_boost = math.log1p(entry.get("access_count", 0)) * 0.2
    return decay + access_boost


# ── UserMemory class ────────────────────────────────────────────────────────

class UserMemory:
    """Per-user memory store backed by a JSON file."""

    def __init__(self, username: str):
        self.username = re.sub(r"[^a-zA-Z0-9_\-]", "", username or "")
        if not self.username:
            raise ValueError("Invalid username")
        self.path = MEMORY_DIR / f"{self.username}.json"
        self._lock = _get_lock(self.username)

    @staticmethod
    def _default_data() -> dict:
        return {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": [],
        }

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # Ensure structure is valid
            if not isinstance(data, dict):
                data = self._default_data()
            if "short_term" not in data or not isinstance(data["short_term"], dict):
                data["short_term"] = {cat: [] for cat in SHORT_TERM_CATEGORIES}

            # Migration: drop old short-term categories
            for old_cat in _OLD_SHORT_TERM_CATEGORIES:
                data["short_term"].pop(old_cat, None)

            # Ensure new short-term categories exist
            for cat in SHORT_TERM_CATEGORIES:
                if cat not in data["short_term"] or not isinstance(data["short_term"][cat], list):
                    data["short_term"][cat] = []

            if "long_term" not in data or not isinstance(data["long_term"], list):
                data["long_term"] = []
            data["long_term"] = [_backfill_entry(e) for e in data["long_term"]]

            # Migration: remove long-term entries auto-promoted from page_visits
            data["long_term"] = [
                e for e in data["long_term"]
                if e.get("context") != "Auto-promoted from repeated page_visits"
            ]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = self._default_data()
        self.cleanup(data)
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def cleanup(self, data: dict) -> None:
        """Remove expired entries and enforce FIFO limits."""
        now = time.time()
        # Short-term: remove expired, enforce FIFO
        for cat in SHORT_TERM_CATEGORIES:
            entries = data["short_term"].get(cat, [])
            entries = [
                e for e in entries
                if e.get("ttl") is None or (e.get("ts", 0) + e["ttl"]) > now
            ]
            if len(entries) > MAX_PER_CATEGORY:
                entries = entries[-MAX_PER_CATEGORY:]
            data["short_term"][cat] = entries
        # Long-term: remove expired (ttl not None)
        data["long_term"] = [
            e for e in data["long_term"]
            if e.get("ttl") is None or (e.get("ts", 0) + e["ttl"]) > now
        ]

    def track(self, category: str, value: str, ttl: int | None = None) -> dict:
        """Add an entry to short-term memory."""
        if category not in SHORT_TERM_CATEGORIES:
            raise ValueError(f"Invalid short-term category: {category}")
        entry = {
            "key": str(uuid.uuid4()),
            "value": value,
            "ts": time.time(),
            "ttl": ttl if ttl is not None else DEFAULT_SHORT_TERM_TTL,
        }
        with self._lock:
            data = self._load()
            data["short_term"][category].append(entry)
            # FIFO prune
            if len(data["short_term"][category]) > MAX_PER_CATEGORY:
                data["short_term"][category] = data["short_term"][category][-MAX_PER_CATEGORY:]
            self._save(data)
        return entry

    def remember(self, category: str, value: str, key: str | None = None,
                 notes: str | None = None, ttl: int | None = None,
                 context: str | None = None, evergreen: bool = False) -> dict:
        """Upsert an entry in long-term memory."""
        if category not in LONG_TERM_CATEGORIES:
            raise ValueError(f"Invalid long-term category: {category}")
        if key is None:
            key = f"{category}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            data = self._load()
            # Check for existing entry with same key (upsert)
            for i, entry in enumerate(data["long_term"]):
                if entry.get("key") == key:
                    data["long_term"][i] = {
                        "key": key,
                        "category": category,
                        "value": value,
                        "notes": notes,
                        "context": context,
                        "evergreen": evergreen,
                        "access_count": entry.get("access_count", 0),
                        "ts": time.time(),
                        "ttl": ttl,
                    }
                    self._save(data)
                    return data["long_term"][i]
            # New entry
            entry = {
                "key": key,
                "category": category,
                "value": value,
                "notes": notes,
                "context": context,
                "evergreen": evergreen,
                "access_count": 0,
                "ts": time.time(),
                "ttl": ttl,
            }
            data["long_term"].append(entry)
            self._save(data)
        return entry

    def forget(self, key: str) -> bool:
        """Remove an entry by key from long-term or short-term memory."""
        with self._lock:
            data = self._load()
            # Try long-term first
            for i, entry in enumerate(data["long_term"]):
                if entry.get("key") == key:
                    data["long_term"].pop(i)
                    self._save(data)
                    return True
            # Try short-term
            for cat in SHORT_TERM_CATEGORIES:
                for i, entry in enumerate(data["short_term"][cat]):
                    if entry.get("key") == key:
                        data["short_term"][cat].pop(i)
                        self._save(data)
                        return True
        return False

    def get_all(self) -> dict:
        """Return the full cleaned memory dict."""
        with self._lock:
            data = self._load()
            self._save(data)  # persist any cleanup
        return data

    def get_summary(self, max_items: int = 10) -> str:
        """Return a text summary for system prompt injection."""
        with self._lock:
            data = self._load()
            self._promote(data)

            # Score and rank long-term entries
            now = time.time()
            lt = data.get("long_term", [])
            scored = sorted(lt, key=lambda e: _relevance_score(e, now), reverse=True)
            top = scored[:max_items]

            # Increment access_count on selected entries
            top_keys = {e["key"] for e in top}
            for entry in lt:
                if entry["key"] in top_keys:
                    entry["access_count"] = entry.get("access_count", 0) + 1

            self._save(data)

        lines = []

        # Long-term memories
        if top:
            lines.append("Long-term memories:")
            for entry in top:
                cat = entry.get("category", "unknown")
                val = entry.get("value", "")
                notes = entry.get("notes")
                ctx = entry.get("context")
                line = f"  - [{cat}] {val}"
                if notes:
                    line += f" ({notes})"
                if ctx:
                    line += f" | context: {ctx}"
                lines.append(line)
            if len(lt) > max_items:
                lines.append(f"  ... and {len(lt) - max_items} more")

        # Short-term sections
        remaining = max_items - len(top)
        if remaining > 0:
            st = data.get("short_term", {})
            section_map = [
                ("recent_conversations", "Recent conversations:"),
                ("recent_plans", "Active plans:"),
                ("health_status", "Recent health status:"),
            ]
            for cat, heading in section_map:
                entries = st.get(cat, [])
                if not entries or remaining <= 0:
                    continue
                lines.append(heading)
                for entry in entries[-remaining:]:
                    lines.append(f"  - {entry.get('value', '')}")
                    remaining -= 1
                    if remaining <= 0:
                        break

        return "\n".join(lines)

    def _promote(self, data: dict) -> list[str]:
        """Promote frequently repeated recent_conversations entries to long-term memory.

        Only recent_conversations are eligible for promotion (repeated topics
        become long-term facts). recent_plans and health_status are inherently
        ephemeral and are never promoted.
        """
        promoted_keys = []
        entries = data["short_term"].get("recent_conversations", [])
        counts: dict[str, int] = {}
        for e in entries:
            val = e.get("value", "")
            counts[val] = counts.get(val, 0) + 1

        for value, count in counts.items():
            if count < PROMOTION_THRESHOLD:
                continue
            # Check for duplicate in long-term
            if any(e.get("value") == value for e in data["long_term"]):
                continue
            promoted_key = f"promoted-{uuid.uuid4().hex[:8]}"
            new_entry = {
                "key": promoted_key,
                "category": "fact",
                "value": value,
                "notes": None,
                "context": "Auto-promoted from repeated recent_conversations",
                "evergreen": False,
                "access_count": 0,
                "ts": time.time(),
                "ttl": None,
            }
            data["long_term"].append(new_entry)
            promoted_keys.append(promoted_key)
            # Remove promoted entries from short-term
            data["short_term"]["recent_conversations"] = [
                e for e in data["short_term"]["recent_conversations"]
                if e.get("value") != value
            ]
        return promoted_keys


# ── Flask Blueprint ──────────────────────────────────────────────────────────

memory_bp = Blueprint("memory", __name__)


def _require_auth():
    """Return username if logged in, else None."""
    if current_user.is_authenticated:
        return current_user.email
    return session.get("username")


@memory_bp.route("/api/memory", methods=["GET"])
def api_get_memory():
    username = _require_auth()
    if not username:
        return jsonify(success=False, message="Login required"), 401
    try:
        mem = UserMemory(username)
        return jsonify(success=True, memory=mem.get_all())
    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400


@memory_bp.route("/api/memory", methods=["POST"])
def api_remember():
    username = _require_auth()
    if not username:
        return jsonify(success=False, message="Login required"), 401
    body = request.get_json(force=True) or {}
    category = body.get("category", "")
    value = (body.get("value") or "").strip()
    key = body.get("key")
    notes = body.get("notes")
    ttl = body.get("ttl")
    context = body.get("context")
    evergreen = body.get("evergreen", False)

    if not value:
        return jsonify(success=False, message="value is required"), 400
    if len(value) > 500:
        return jsonify(success=False, message="value must be 500 characters or less"), 400
    if category not in LONG_TERM_CATEGORIES:
        return jsonify(success=False, message=f"category must be one of {LONG_TERM_CATEGORIES}"), 400
    if ttl is not None:
        if not isinstance(ttl, (int, float)) or ttl < 0:
            return jsonify(success=False, message="ttl must be a non-negative number"), 400
    if key and len(key) > 200:
        return jsonify(success=False, message="key must be 200 characters or less"), 400
    if notes and len(notes) > 500:
        return jsonify(success=False, message="notes must be 500 characters or less"), 400
    if context is not None:
        if not isinstance(context, str) or len(context) > 500:
            return jsonify(success=False, message="context must be a string of 500 characters or less"), 400
    if not isinstance(evergreen, bool):
        return jsonify(success=False, message="evergreen must be a boolean"), 400

    try:
        mem = UserMemory(username)
        entry = mem.remember(category, value, key=key, notes=notes, ttl=ttl,
                             context=context, evergreen=evergreen)
        return jsonify(success=True, entry=entry)
    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400


@memory_bp.route("/api/memory/<key>", methods=["DELETE"])
def api_forget(key):
    username = _require_auth()
    if not username:
        return jsonify(success=False, message="Login required"), 401
    try:
        mem = UserMemory(username)
        found = mem.forget(key)
        if found:
            return jsonify(success=True)
        return jsonify(success=False, message="Key not found"), 404
    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400


@memory_bp.route("/api/memory/track", methods=["POST"])
def api_track():
    username = _require_auth()
    if not username:
        return jsonify(success=False, message="Login required"), 401
    body = request.get_json(force=True) or {}
    category = body.get("category", "")
    value = (body.get("value") or "").strip()
    ttl = body.get("ttl")

    if not value:
        return jsonify(success=False, message="value is required"), 400
    if len(value) > 200:
        return jsonify(success=False, message="value must be 200 characters or less"), 400
    if category not in SHORT_TERM_CATEGORIES:
        return jsonify(success=False, message=f"category must be one of {SHORT_TERM_CATEGORIES}"), 400
    if ttl is not None:
        if not isinstance(ttl, (int, float)) or ttl < 0:
            return jsonify(success=False, message="ttl must be a non-negative number"), 400

    try:
        mem = UserMemory(username)
        entry = mem.track(category, value, ttl=ttl)
        return jsonify(success=True, entry=entry)
    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400


@memory_bp.route("/settings/memory")
@login_required
def settings_memory_page():
    """Render settings memory page."""
    username = _require_auth()
    return render_template(
        "settings_memory.html",
        username=username,
        settings_section="memory",
    )

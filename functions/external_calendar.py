"""External calendar integration via iCal URL import.

Fetches, caches, and formats external calendar events so the agent can
plan around the user's existing schedule (avoid conflicts, suggest free slots).
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from icalendar import Calendar

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
CALENDAR_DIR = APP_DIR / "personal_data" / "calendars"
CALENDAR_DIR.mkdir(parents=True, exist_ok=True)

calendar_settings_bp = Blueprint("calendar_settings", __name__)

_cache_lock = threading.Lock()
_event_cache: dict[str, dict] = {}  # username -> {"fetched_at": float, "events": [...]}
CACHE_TTL = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------

def _config_path(username: str) -> Path:
    return CALENDAR_DIR / f"{username}_feeds.json"


def _load_feeds(username: str) -> list[dict]:
    p = _config_path(username)
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("Failed to load calendar feeds for %s: %s", username, exc)
        return []


def _save_feeds(username: str, feeds: list[dict]) -> None:
    p = _config_path(username)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(feeds, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# iCal fetching & parsing
# ---------------------------------------------------------------------------

def _fetch_ical(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch raw iCal text from a URL."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "DREAM-Chat/1.0 (iCal reader)",
            "Accept": "text/calendar",
        })
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch iCal from %s: %s", url, exc)
        return None


def _parse_events(ical_text: str, days_ahead: int = 14) -> list[dict]:
    """Parse iCal text and return current/future events within the time window."""
    try:
        cal = Calendar.from_ical(ical_text)
    except Exception as exc:
        logger.warning("Failed to parse iCal data: %s", exc)
        return []

    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day)
    window_end = now + timedelta(days=days_ahead)
    events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        summary = str(component.get("summary", ""))
        location = str(component.get("location", ""))
        description = str(component.get("description", ""))

        if not dtstart:
            continue

        dt_val = dtstart.dt
        # Handle all-day events (date vs datetime)
        if isinstance(dt_val, date) and not isinstance(dt_val, datetime):
            start = datetime(dt_val.year, dt_val.month, dt_val.day)
            is_all_day = True
        else:
            start = dt_val.replace(tzinfo=None) if hasattr(dt_val, "replace") else dt_val
            is_all_day = False

        if start < today_start or start > window_end:
            continue

        end = None
        if dtend:
            end_val = dtend.dt
            if isinstance(end_val, date) and not isinstance(end_val, datetime):
                end = datetime(end_val.year, end_val.month, end_val.day)
            else:
                end = end_val.replace(tzinfo=None) if hasattr(end_val, "replace") else end_val

        event = {
            "summary": summary.strip(),
            "start": start.isoformat(),
            "is_all_day": is_all_day,
        }
        if end:
            event["end"] = end.isoformat()
        if location and location.strip():
            event["location"] = location.strip()
        if description and description.strip() and len(description.strip()) < 200:
            event["description"] = description.strip()

        events.append(event)

    events.sort(key=lambda e: e["start"])
    return events


def _invalidate_cache(username: str) -> None:
    with _cache_lock:
        _event_cache.pop(username, None)


# ---------------------------------------------------------------------------
# Public API for skills
# ---------------------------------------------------------------------------

def get_upcoming_events(username: str, days_ahead: int = 14) -> list[dict]:
    """Return cached upcoming events, refreshing from feeds if stale."""
    with _cache_lock:
        cached = _event_cache.get(username)
        if cached and (time.time() - cached["fetched_at"]) < CACHE_TTL:
            return cached["events"]

    feeds = _load_feeds(username)
    if not feeds:
        return []

    all_events = []
    for feed in feeds:
        if not feed.get("enabled", True):
            continue
        url = feed.get("url", "")
        if not url:
            continue
        ical_text = _fetch_ical(url)
        if ical_text:
            events = _parse_events(ical_text, days_ahead=days_ahead)
            for ev in events:
                ev["calendar"] = feed.get("name", "Calendar")
            all_events.extend(events)

    all_events.sort(key=lambda e: e["start"])

    with _cache_lock:
        _event_cache[username] = {"fetched_at": time.time(), "events": all_events}

    return all_events


def format_events_for_context(events: list[dict], max_events: int = 30) -> str:
    """Format events into a concise text block for the system prompt."""
    if not events:
        return ""

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    lines = []
    current_date = None

    for ev in events[:max_events]:
        start = datetime.fromisoformat(ev["start"])
        date_str = start.strftime("%Y-%m-%d")

        if date_str != current_date:
            current_date = date_str
            if date_str == today_str:
                day_label = "Today"
            elif date_str == tomorrow_str:
                day_label = "Tomorrow"
            else:
                day_label = start.strftime("%A, %b %d")
            lines.append(f"\n**{day_label}** ({date_str})")

        if ev.get("is_all_day"):
            time_str = "All day"
        else:
            time_str = start.strftime("%I:%M %p").lstrip("0")
            if ev.get("end"):
                end = datetime.fromisoformat(ev["end"])
                time_str += f" - {end.strftime('%I:%M %p').lstrip('0')}"

        entry = f"  - {time_str}: {ev['summary']}"
        if ev.get("location"):
            entry += f" @ {ev['location']}"
        if ev.get("calendar"):
            entry += f" [{ev['calendar']}]"
        lines.append(entry)

    return "\n".join(lines).strip()


def has_feeds(username: str) -> bool:
    """Check if a user has any calendar feeds configured."""
    feeds = _load_feeds(username)
    return bool(feeds)


# ---------------------------------------------------------------------------
# Flask routes — settings UI + API
# ---------------------------------------------------------------------------

def _require_login():
    return current_user.is_authenticated


def _username() -> Optional[str]:
    if current_user.is_authenticated:
        return current_user.email
    return session.get("username")


@calendar_settings_bp.route("/settings/calendars")
@login_required
def settings_calendars_page():
    """Render the calendar feeds settings page."""
    return render_template(
        "settings_calendars.html",
        username=_username(),
        settings_section="calendars",
    )


@calendar_settings_bp.route("/api/settings/calendars", methods=["GET"])
def api_list_feeds():
    """List all calendar feeds for the logged-in user."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    feeds = _load_feeds(_username())
    # Strip actual URL from response for display safety — show domain only
    safe_feeds = []
    for f in feeds:
        safe = {**f}
        try:
            parsed = urlparse(f.get("url", ""))
            safe["domain"] = parsed.netloc or "unknown"
        except Exception:
            safe["domain"] = "unknown"
        safe_feeds.append(safe)
    return jsonify(success=True, feeds=safe_feeds)


@calendar_settings_bp.route("/api/settings/calendars", methods=["POST"])
def api_add_feed():
    """Add a new iCal feed URL."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    name = (data.get("name") or "").strip() or "My Calendar"

    if not url:
        return jsonify(success=False, message="URL is required"), 400

    # Basic URL validation
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "webcal"):
        return jsonify(success=False, message="URL must start with http://, https://, or webcal://"), 400

    # Normalize webcal:// to https://
    if parsed.scheme == "webcal":
        url = "https://" + url[len("webcal://"):]

    # Verify the URL is actually an iCal feed
    ical_text = _fetch_ical(url)
    if not ical_text:
        return jsonify(success=False, message="Could not fetch the calendar URL. Please check the URL and try again."), 400

    try:
        Calendar.from_ical(ical_text)
    except Exception:
        return jsonify(success=False, message="The URL does not appear to be a valid iCal feed."), 400

    username = _username()
    feeds = _load_feeds(username)

    # Check for duplicate URL
    for f in feeds:
        if f.get("url") == url:
            return jsonify(success=False, message="This calendar URL is already added."), 409

    import uuid
    feed_id = uuid.uuid4().hex[:12]
    feeds.append({
        "feed_id": feed_id,
        "name": name,
        "url": url,
        "enabled": True,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_feeds(username, feeds)
    _invalidate_cache(username)

    # Count events to give feedback
    events = _parse_events(ical_text)
    return jsonify(success=True, feed_id=feed_id, event_count=len(events))


@calendar_settings_bp.route("/api/settings/calendars/<feed_id>", methods=["DELETE"])
def api_delete_feed(feed_id):
    """Remove a calendar feed."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    username = _username()
    feeds = _load_feeds(username)
    original_len = len(feeds)
    feeds = [f for f in feeds if f.get("feed_id") != feed_id]
    if len(feeds) == original_len:
        return jsonify(success=False, message="Feed not found"), 404

    _save_feeds(username, feeds)
    _invalidate_cache(username)
    return jsonify(success=True)


@calendar_settings_bp.route("/api/settings/calendars/<feed_id>/toggle", methods=["POST"])
def api_toggle_feed(feed_id):
    """Enable or disable a calendar feed."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    data = request.get_json(force=True)
    enabled = data.get("enabled", True)

    username = _username()
    feeds = _load_feeds(username)
    found = False
    for f in feeds:
        if f.get("feed_id") == feed_id:
            f["enabled"] = bool(enabled)
            found = True
            break

    if not found:
        return jsonify(success=False, message="Feed not found"), 404

    _save_feeds(username, feeds)
    _invalidate_cache(username)
    return jsonify(success=True)


@calendar_settings_bp.route("/api/settings/calendars/preview", methods=["GET"])
def api_preview_events():
    """Preview upcoming events from all enabled feeds."""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    username = _username()
    events = get_upcoming_events(username)
    return jsonify(success=True, events=events, count=len(events))

"""User Memory module for DREAM-Chat.

Internal memory system that stores per-user context in markdown files.
Short-term memory captures recent conversations, plans, and health status.
Long-term memory stores preferences, facts, goals, and saved items.
Not exposed to users via UI — purely used to provide better service.
"""

import re
import threading
from datetime import datetime
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

SHORT_TERM_CATEGORIES = ["recent_conversations", "recent_plans", "health_status"]
LONG_TERM_CATEGORIES = ["preference", "fact", "saved", "goal"]
MAX_PER_CATEGORY = 20
PROMOTION_THRESHOLD = 3

MEMORY_DIR = Path(__file__).resolve().parent.parent / "personal_data" / "memory"

_SECTION_HEADINGS = {
    "preference": "Preferences",
    "fact": "Facts",
    "saved": "Saved",
    "goal": "Goals",
    "recent_conversations": "Recent Conversations",
    "recent_plans": "Recent Plans",
    "health_status": "Health Status",
}

# ── Per-user locks ───────────────────────────────────────────────────────────

_user_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_lock(username: str) -> threading.Lock:
    with _locks_lock:
        if username not in _user_locks:
            _user_locks[username] = threading.Lock()
        return _user_locks[username]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── Entry normalization ─────────────────────────────────────────────────────

FILLER_PREFIXES = [
    r"^(?:the )?user(?:'s)?\s+(?:prefers?|likes?|wants?|has|is|mentioned|said|noted|reported|follows?|enjoys?|needs?|asked|discussed|talked)\s+(?:about\s+)?",
    r"^(?:remember|note|save|store|record)(?:\s+that)?\s*:?\s*",
    r"^(?:preference|fact|goal|note):\s*",
    r"^(?:it is|this is|they are|he is|she is)\s+(?:noted|known|important)?\s*(?:that)?\s*",
]

KEY_SYNONYMS: dict[str, str] = {
    "dietary_preference": "diet",
    "food_preference": "diet",
    "dietary_restriction": "diet",
    "exercise_preference": "exercise",
    "workout_preference": "exercise",
    "sleep_preference": "sleep",
    "sleep_schedule": "sleep",
    "weight_goal": "weight",
    "fitness_goal": "fitness",
    "health_goal": "fitness",
    "body_weight": "weight",
    "body_height": "height",
    "birth_date": "age",
    "birthday": "age",
    "medication": "medications",
    "med": "medications",
    "supplement": "supplements",
    "injury": "injuries",
    "medical_condition": "condition",
    "health_condition": "condition",
    "chronic_condition": "condition",
}

KEY_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:vegan|vegetarian|keto|paleo|diet|eat|food|meal)\b", "diet"),
    (r"\b(?:allerg|intoleran)", "allergy"),
    (r"\b(?:exercis|workout|training|gym|runn|swim|yoga|jog|cycl|hik)", "exercise"),
    (r"\b(?:sleep|wake|bedtime|insomnia)\b", "sleep"),
    (r"(?:\bweight|(?:\d\s*)kg\b|(?:\d\s*)lbs?\b|\bpounds?\b|\bweigh)", "weight"),
    (r"(?:\bheight|\b(?:\d\s*)cm\b|\bfeet\b|\btall\b)", "height"),
    (r"\b(?:age|born|birthday|years old)\b", "age"),
    (r"\b(?:medic|prescription|drug|pill)\b", "medications"),
    (r"\b(?:supplement|vitamin|mineral)\b", "supplements"),
    (r"\b(?:injur|sprain|strain|fracture|torn)\b", "injuries"),
    (r"\b(?:diabet|asthma|hypertension|cholesterol)\b", "condition"),
    (r"\b(?:goal|target|aim|objective)\b", "goal"),
    (r"\b(?:schedule|routine|habit)\b", "routine"),
]

_FILLER_RES = [re.compile(p, re.IGNORECASE) for p in FILLER_PREFIXES]

_TOPIC_FILLER_PREFIXES = [
    r"^(?:the )?user(?:'s)?\s+(?:prefers?|likes?|wants?|has|is|mentioned|said|noted|reported|follows?|enjoys?|needs?|asked|discussed|talked)\s+(?:about\s+)?",
    r"^(?:it is|this is|they are|he is|she is)\s+(?:noted|known|important)?\s*(?:that)?\s*",
]
_TOPIC_FILLER_RES = [re.compile(p, re.IGNORECASE) for p in _TOPIC_FILLER_PREFIXES]


def _strip_filler(text: str, patterns: list[re.Pattern]) -> str:
    """Repeatedly strip matching filler prefixes until stable."""
    prev = None
    while prev != text:
        prev = text
        for pat in patterns:
            text = pat.sub("", text).strip()
    return text


def _slugify_key(raw: str) -> str:
    """Convert a raw key string to canonical slug form."""
    s = raw.lower().strip()
    s = s.replace("_", "-").replace(" ", "-")
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:40]


def _resolve_synonym(key: str) -> str:
    """Map a key through KEY_SYNONYMS (underscore-normalized lookup)."""
    lookup = key.lower().strip().replace("-", "_").replace(" ", "_")
    return KEY_SYNONYMS.get(lookup, key)


def _infer_key(value: str) -> str | None:
    """Try to infer a canonical key from value content via KEY_PATTERNS."""
    lower = value.lower()
    for pattern, key in KEY_PATTERNS:
        if re.search(pattern, lower):
            return key
    return None


def normalize_entry(value: str, category: str, key: str | None = None,
                    notes: str | None = None, context: str | None = None) -> tuple[str, str]:
    """Normalize a memory entry into canonical ``key: value`` format.

    Returns ``(normalized_key, entry_line)`` where *entry_line* is the full
    string to store in the markdown file.

    Raises ``ValueError`` if *value* is empty after stripping.
    """
    # 1. Strip filler prefixes and sanitize newlines
    cleaned = value.strip().replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _strip_filler(cleaned, _FILLER_RES)

    if not cleaned:
        raise ValueError("value is empty after stripping filler")

    # 2. Check if value already has "key: value" format
    extracted_key: str | None = None
    extracted_value: str | None = None
    colon_match = re.match(r"^([a-zA-Z0-9_\- ]{1,40}):\s+(.+)$", cleaned)
    if colon_match:
        candidate_key = colon_match.group(1).strip()
        # Only treat as key:value if key part is short (looks like a label)
        if len(candidate_key.split()) <= 3:
            extracted_key = candidate_key
            extracted_value = colon_match.group(2).strip()

    # 3. Determine the key
    if key:
        resolved = _resolve_synonym(key)
        norm_key = _slugify_key(resolved)
    elif extracted_key:
        resolved = _resolve_synonym(extracted_key)
        norm_key = _slugify_key(resolved)
        cleaned = extracted_value or cleaned
    else:
        inferred = _infer_key(cleaned)
        if inferred:
            norm_key = _slugify_key(inferred)
        else:
            norm_key = _slugify_key(category)

    if not norm_key:
        norm_key = _slugify_key(category)

    # 4. Clean the value: strip leading articles/filler, capitalize first word
    cleaned = re.sub(r"^(?:a |an |the )\s*", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]

    # 5. Build entry line (sanitize notes/context for newlines)
    entry_line = f"{norm_key}: {cleaned}"
    if notes:
        notes = notes.replace("\n", " ").strip()
        entry_line += f" ({notes})"
    if context:
        context = context.replace("\n", " ").strip()
        entry_line += f" | context: {context}"

    return (norm_key, entry_line)


def normalize_topic(value: str) -> str:
    """Lightly normalize a short-term topic string.

    Strips "The user mentioned/said/…" style filler but keeps action words
    like "asked about" that carry semantic meaning for conversation context.

    Returns cleaned string (empty string for empty/whitespace input).
    """
    if not value or not value.strip():
        return ""
    cleaned = value.strip().replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _strip_filler(cleaned, _TOPIC_FILLER_RES)
    return cleaned


# ── Markdown parsing / writing ───────────────────────────────────────────────

def _parse_md(text: str) -> dict:
    """Parse a memory markdown file into a structured dict.

    Returns: {
        "long_term": {"preference": [...], "fact": [...], "saved": [...], "goal": [...]},
        "short_term": {"recent_conversations": [...], "recent_plans": [...], "health_status": []},
    }
    Each entry is a string (the bullet text without the leading "- ").
    """
    data = {
        "long_term": {cat: [] for cat in LONG_TERM_CATEGORIES},
        "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
    }

    # Build reverse lookup: heading text -> (layer, category)
    heading_to_key = {}
    for cat, heading in _SECTION_HEADINGS.items():
        if cat in LONG_TERM_CATEGORIES:
            heading_to_key[heading.lower()] = ("long_term", cat)
        else:
            heading_to_key[heading.lower()] = ("short_term", cat)

    current_layer = None
    current_cat = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading_text = stripped[3:].strip().lower()
            if heading_text in heading_to_key:
                current_layer, current_cat = heading_to_key[heading_text]
            else:
                current_layer = None
                current_cat = None
        elif stripped.startswith("- ") and current_layer and current_cat:
            entry = stripped[2:].strip()
            if entry:
                data[current_layer][current_cat].append(entry)

    return data


def _render_md(data: dict) -> str:
    """Render a structured dict back into markdown."""
    lines = ["# User Memory", ""]

    # Long-term sections
    has_lt = any(data["long_term"].get(cat) for cat in LONG_TERM_CATEGORIES)
    if has_lt:
        for cat in LONG_TERM_CATEGORIES:
            entries = data["long_term"].get(cat, [])
            if entries:
                lines.append(f"## {_SECTION_HEADINGS[cat]}")
                for entry in entries:
                    lines.append(f"- {entry}")
                lines.append("")

    # Short-term sections
    for cat in SHORT_TERM_CATEGORIES:
        entries = data["short_term"].get(cat, [])
        if entries:
            lines.append(f"## {_SECTION_HEADINGS[cat]}")
            for entry in entries:
                lines.append(f"- {entry}")
            lines.append("")

    return "\n".join(lines)


# ── UserMemory class ────────────────────────────────────────────────────────

class UserMemory:
    """Per-user memory store backed by a markdown file."""

    def __init__(self, username: str):
        self.username = re.sub(r"[^a-zA-Z0-9_\-]", "", username or "")
        if not self.username:
            raise ValueError("Invalid username")
        self.path = MEMORY_DIR / f"{self.username}.md"
        self._lock = _get_lock(self.username)

    def _load(self) -> dict:
        try:
            text = self.path.read_text(encoding="utf-8")
            return _parse_md(text)
        except (FileNotFoundError, OSError):
            return {
                "long_term": {cat: [] for cat in LONG_TERM_CATEGORIES},
                "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            }

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_render_md(data), encoding="utf-8")

    def track(self, category: str, value: str) -> None:
        """Add an entry to short-term memory."""
        if category not in SHORT_TERM_CATEGORIES:
            raise ValueError(f"Invalid short-term category: {category}")
        value = normalize_topic(value)
        if not value:
            return
        # Truncate long values
        if len(value) > 150:
            value = value[:150] + "..."
        entry = f"{value} ({_today()})"
        with self._lock:
            data = self._load()
            entries = data["short_term"][category]
            # Avoid near-duplicates (same value prefix on same day)
            val_prefix = value[:80]
            entries = [e for e in entries if not e.startswith(val_prefix)]
            entries.append(entry)
            # FIFO prune
            if len(entries) > MAX_PER_CATEGORY:
                entries = entries[-MAX_PER_CATEGORY:]
            data["short_term"][category] = entries
            self._promote(data)
            self._save(data)

    def remember(self, category: str, value: str, key: str | None = None,
                 notes: str | None = None, context: str | None = None,
                 **_kwargs) -> dict:
        """Add or update an entry in long-term memory. Returns a dict with key/value for compatibility."""
        if category not in LONG_TERM_CATEGORIES:
            raise ValueError(f"Invalid long-term category: {category}")
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        if len(value) > 500:
            value = value[:500]

        # Normalize into canonical "key: value" format
        normalized_key, entry_line = normalize_entry(
            value, category, key=key, notes=notes, context=context,
        )

        with self._lock:
            data = self._load()
            entries = data["long_term"][category]

            # Dedup by normalized key prefix: replace existing entry with same key
            key_prefix = normalized_key + ":"
            replaced = False
            for i, existing in enumerate(entries):
                if existing.startswith(key_prefix):
                    entries[i] = entry_line
                    replaced = True
                    break

            if not replaced:
                # Avoid exact duplicates as fallback
                if entry_line not in entries:
                    entries.append(entry_line)

            data["long_term"][category] = entries
            self._save(data)
        return {"key": normalized_key, "value": entry_line}

    def forget(self, key: str) -> bool:
        """Remove an entry by matching text (case-insensitive) from any memory section."""
        key_lower = key.lower()
        with self._lock:
            data = self._load()
            # Search long-term
            for cat in LONG_TERM_CATEGORIES:
                for i, entry in enumerate(data["long_term"][cat]):
                    if key_lower in entry.lower():
                        data["long_term"][cat].pop(i)
                        self._save(data)
                        return True
            # Search short-term
            for cat in SHORT_TERM_CATEGORIES:
                for i, entry in enumerate(data["short_term"][cat]):
                    if key_lower in entry.lower():
                        data["short_term"][cat].pop(i)
                        self._save(data)
                        return True
        return False

    def get_all(self) -> dict:
        """Return the full memory dict."""
        with self._lock:
            return self._load()

    def get_summary(self, max_items: int = 10) -> str:
        """Return a text summary for system prompt injection."""
        with self._lock:
            data = self._load()
            self._promote(data)
            self._save(data)

        lines = []
        count = 0

        # Long-term memories
        for cat in LONG_TERM_CATEGORIES:
            entries = data["long_term"].get(cat, [])
            if entries:
                lines.append(f"{_SECTION_HEADINGS[cat]}:")
                for entry in entries:
                    if count >= max_items:
                        break
                    lines.append(f"  - {entry}")
                    count += 1

        # Short-term memories
        for cat in SHORT_TERM_CATEGORIES:
            entries = data["short_term"].get(cat, [])
            if entries:
                if count >= max_items:
                    break
                lines.append(f"{_SECTION_HEADINGS[cat]}:")
                for entry in entries[-5:]:  # most recent 5 per short-term category
                    if count >= max_items:
                        break
                    lines.append(f"  - {entry}")
                    count += 1

        return "\n".join(lines)

    def _promote(self, data: dict) -> None:
        """Promote frequently repeated conversation topics to long-term facts."""
        entries = data["short_term"].get("recent_conversations", [])
        # Extract just the value part (before the date suffix)
        values = []
        for e in entries:
            # Strip date suffix like " (2026-03-28)"
            val = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", e)
            values.append(val)

        counts: dict[str, int] = {}
        for val in values:
            counts[val] = counts.get(val, 0) + 1

        facts = data["long_term"]["fact"]
        for value, count in counts.items():
            if count < PROMOTION_THRESHOLD:
                continue
            # Normalize promoted entry before appending
            try:
                norm_key, entry_line = normalize_entry(
                    value, "fact", context="auto-promoted from repeated conversations",
                )
            except ValueError:
                continue
            # Check for duplicate in long-term facts (by key prefix or content)
            key_prefix = norm_key + ":"
            if any(f.startswith(key_prefix) or value in f for f in facts):
                continue
            facts.append(entry_line)
            # Remove promoted entries from short-term
            data["short_term"]["recent_conversations"] = [
                e for e in data["short_term"]["recent_conversations"]
                if not e.startswith(value)
            ]

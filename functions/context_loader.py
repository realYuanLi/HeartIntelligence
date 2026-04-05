"""Loads and assembles markdown context files into a system prompt."""

import json
import logging
import threading
from pathlib import Path

from .md_utils import _parse_frontmatter

logger = logging.getLogger(__name__)

CONTEXT_DIR = Path(__file__).resolve().parent.parent / "context"
CONTEXT_STATE_PATH = Path(__file__).resolve().parent.parent / "config" / "context_settings.json"
_context_state_lock = threading.Lock()


def _load_context_state(path: Path = CONTEXT_STATE_PATH) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): bool(v) for k, v in data.items()}
    except Exception as exc:
        logger.warning("Failed to load context state from %s: %s", path, exc)
        return {}


def _save_context_state(state: dict[str, bool], path: Path = CONTEXT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_context_files(context_dir: Path = CONTEXT_DIR) -> str:
    """Glob context/*.md, filter by enabled state, sort by filename, concatenate."""
    if not context_dir.exists():
        logger.warning("Context directory not found: %s", context_dir)
        return ""

    state = _load_context_state()
    bodies = []

    for path in sorted(context_dir.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            ctx_id = meta.get("id") or path.stem

            if ctx_id in state and not state[ctx_id]:
                continue

            bodies.append(body)
        except Exception as exc:
            logger.error("Failed to load context file %s: %s", path, exc)

    return "\n\n".join(bodies)


def list_context_files(context_dir: Path = CONTEXT_DIR) -> list[dict]:
    """Return metadata for all context files."""
    if not context_dir.exists():
        return []

    state = _load_context_state()
    items = []

    for path in sorted(context_dir.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(raw)
            ctx_id = meta.get("id") or path.stem
            enabled = state.get(ctx_id, True)

            items.append({
                "id": ctx_id,
                "enabled": enabled,
            })
        except Exception as exc:
            logger.error("Failed to load context file %s: %s", path, exc)

    return items


def set_context_enabled(ctx_id: str, enabled: bool) -> None:
    """Toggle a context file on/off, persisted to config/context_settings.json."""
    with _context_state_lock:
        state = _load_context_state()
        state[ctx_id] = bool(enabled)
        _save_context_state(state)

"""Shared markdown utilities for frontmatter parsing."""


def _parse_bool(value: str, default: bool) -> bool:
    lowered = (value or "").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    text = raw.strip()
    if not text.startswith("---"):
        return {}, raw

    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx is None:
        return {}, raw

    meta_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).strip()
    meta: dict = {}
    for line in meta_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body

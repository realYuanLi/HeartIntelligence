# Standardized Memory Entry Normalization
**Date**: 2026-03-28  |  **Status**: Completed

## What Was Built
Rule-based normalization layer for the UserMemory system that ensures different LLMs produce consistent, structured memory entries. When any LLM calls `manage_memory` to remember something, the entry is normalized into a canonical `key: value` format before saving to the markdown file. This eliminates variance between LLM phrasings (e.g., "User prefers vegan diet" vs "preference: vegan" vs "Follows strict vegan diet" all become `diet: Vegan diet`).

## Architecture
Normalization happens at the `UserMemory` layer — no changes to `agent.py` or LLM prompts. Two functions: `normalize_entry()` for long-term memories (full key extraction + formatting) and `normalize_topic()` for short-term conversation tracking (lighter filler stripping). Entry keys are resolved through a 4-level priority chain: explicit key param > synonym resolution > pattern inference > category fallback.

## Key Files
| File | Purpose |
|------|---------|
| `functions/user_memory.py` | Normalization functions, constants, and integration into `remember()`/`track()`/`_promote()` |
| `tests/test_user_memory.py` | 83 tests including normalization, LLM equivalence, deduplication |

## Technical Decisions
- **Rule-based, not LLM-based**: No additional API calls. Deterministic, fast, testable.
- **Key-based deduplication**: `remember()` replaces entries with the same normalized key prefix, so different phrasings of the same fact converge to one entry.
- **Conservative topic normalization**: Only strips "The user mentioned/said/..." filler from short-term entries, preserving action words like "asked about".
- **Case-insensitive forget**: `forget()` uses case-insensitive matching since normalization capitalizes values.

## Testing
```bash
python3 -m pytest tests/test_user_memory.py -v
```
83 tests covering: normalize_entry, normalize_topic, LLM phrasing equivalence, remember/track/forget with normalization, promotion normalization, edge cases (newlines, unicode, length caps).

## Known Limitations
- English-only filler patterns; other languages pass through unnormalized.
- No semantic deduplication — entries with different keys but similar meaning both stored.
- Existing entries in memory files are not retroactively normalized.

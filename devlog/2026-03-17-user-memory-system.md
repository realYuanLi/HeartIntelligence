# User Memory System
**Date**: 2026-03-17  |  **Status**: Completed

## What Was Built
A persistent per-user memory system with two layers: **short-term** (auto-expiring, FIFO-pruned) for behavioral tracking like page visits and chat topics, and **long-term** (permanent by default) for user preferences, facts, saved items, and goals. The LLM proactively calls the memory tool when users reveal personal details, and users can manually manage memories through a Settings UI.

## Architecture
`UserMemory` stores each user's data in a JSON file under `personal_data/memory/{username}.json`. The LLM agent exposes a `manage_memory` tool (remember/forget/recall) that the model calls mid-conversation. On each load, cleanup runs to expire TTL-based entries and enforce FIFO caps (20 per short-term category). A Flask Blueprint provides REST endpoints consumed by the settings page. `get_summary()` injects stored memories into the system prompt for context-aware responses.

## Key Files
| File | Purpose |
|------|---------|
| `functions/user_memory.py` | `UserMemory` class + Flask Blueprint with CRUD endpoints |
| `functions/agent.py` | `MEMORY_TOOL` definition + `manage_memory` handler (lines 98-377) |
| `skills/user_memory.md` | Skill trigger config (keyword-based, priority 5) |
| `templates/settings_memory.html` | Settings UI with add form, long-term/short-term lists |
| `static/settings_memory.js` | Frontend: load, render, add, delete memories via `/api/memory` |
| `tests/test_user_memory.py` | 40+ tests covering class, TTL, FIFO, persistence, API |

## Technical Decisions
- **JSON file per user** instead of a database -- keeps deployment simple and aligns with the existing `personal_data/` pattern. Thread-safe via per-user locks.
- **Two-layer model** -- short-term categories (`page_visits`, `chat_topics`, `recent_searches`, `last_used_skills`) auto-expire with a 7-day default TTL and cap at 20 entries. Long-term entries default to `ttl=None` (permanent).
- **Upsert by key** -- calling `remember` with an existing key updates in place rather than duplicating entries.
- **Username sanitization** -- regex strips everything except `[a-zA-Z0-9_-]` to prevent path traversal.

## Usage
```bash
# API: store a preference
curl -X POST /api/memory -d '{"category":"preference","value":"vegetarian diet"}'

# API: track a page visit (short-term)
curl -X POST /api/memory/track -d '{"category":"page_visits","value":"/dashboard"}'

# In chat: "Remember that I'm allergic to shellfish"
# The LLM auto-calls manage_memory(action="remember", category="fact", value="Allergic to shellfish")
```

## Testing
```bash
pytest tests/test_user_memory.py -v
```
Covers: remember/forget/track CRUD, upsert behavior, TTL expiry (mocked time), FIFO pruning at 20-entry cap, cross-instance persistence, user isolation, username sanitization, corrupted/malformed JSON recovery, and all Flask API endpoints including auth, validation, and error codes.

## Known Limitations
- **No search/filter** -- `get_summary()` returns entries in insertion order with a hard `max_items` cap; no semantic search or relevance ranking.
- **Single-process file locking** -- `threading.Lock` protects concurrent writes within one process but not across multiple workers (e.g., gunicorn with `--workers > 1`).
- **No pagination** -- the settings UI loads all memories at once; could become slow with hundreds of entries.
- **Memory summary truncation** -- system prompt injection is capped at 10 items by default, so older long-term memories may not influence the LLM.

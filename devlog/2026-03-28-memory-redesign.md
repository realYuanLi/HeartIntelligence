# Memory System Redesign: Noise-Free Short-Term Categories
**Date**: 2026-03-28  |  **Status**: Completed

## What Was Built
Redesigned the user memory short-term layer to eliminate navigation noise. Replaced the four original categories (`page_visits`, `chat_topics`, `recent_searches`, `last_used_skills`) with three intent-driven categories: `recent_conversations`, `recent_plans`, and `health_status`. Only `recent_conversations` can auto-promote to long-term memory (at threshold of 3 repeats); the other two are inherently ephemeral. A lazy migration in `_load()` strips old categories and removes long-term entries that were auto-promoted from `page_visits`.

## Architecture
Each user's memory is a JSON file under `personal_data/memory/{username}.json` with `short_term` (category-keyed lists) and `long_term` (flat list). On every `_load()`, the migration runs: old category keys are popped, new ones are ensured, and long-term entries with context `"Auto-promoted from repeated page_visits"` are purged. The agent (`agent.py:484-493`) calls `UserMemory.track("recent_conversations", ...)` on every user message, feeding the promotion pipeline. `get_summary()` triggers `_promote()`, which counts duplicate values in `recent_conversations` and promotes entries at the threshold to long-term `fact` entries, then removes them from short-term. Long-term entries are ranked by a relevance score combining exponential decay (30-day half-life), access count boost, and an evergreen flag.

## Key Files
| File | Purpose |
|---|---|
| `functions/user_memory.py` | `UserMemory` class, FIFO/TTL cleanup, promotion logic, relevance scoring, Flask CRUD blueprint |
| `functions/agent.py` (L484-493) | Auto-tracks conversation topics into `recent_conversations` on each message |
| `tests/test_user_memory.py` | 136 tests across 13 test classes (1430 lines) |

## Technical Decisions
- **Only `recent_conversations` promotes** -- plans and health status are transient by nature; promoting them would reintroduce noise.
- **Lazy migration on `_load()`** -- no separate migration script needed; existing files heal automatically on next access.
- **Page-visit promotion cleanup** -- long-term entries created by the old `page_visits` promoter are actively removed, not just orphaned.
- **Relevance scoring with evergreen flag** -- evergreen entries bypass decay entirely (score = 1.0), ensuring permanent facts like birthdays always surface.

## Usage
```bash
# Run the memory tests
pytest tests/test_user_memory.py -v

# Track a conversation (programmatic)
from functions.user_memory import UserMemory
mem = UserMemory("alice")
mem.track("recent_conversations", "asked about knee exercises")

# Store a long-term memory
mem.remember("preference", "Vegan diet", key="diet", context="meal planning", evergreen=True)

# Get ranked summary for system prompt
print(mem.get_summary(max_items=10))
```

## Testing
Run `pytest tests/test_user_memory.py -v`. 136 tests cover: CRUD operations, TTL expiry (mocked time), FIFO pruning, persistence across instances, user isolation, username sanitization, corrupted/malformed file recovery, all Flask API endpoints with auth, context/evergreen fields, relevance scoring formula, promotion logic (threshold, dedup, removal, category restrictions), and migration from old categories.

## Known Limitations
- **No cross-process locking** -- `threading.Lock` protects concurrent access within a single process but not across multiple workers (e.g., gunicorn with multiple processes writing to the same JSON file).
- **Promotion is value-exact** -- "knee pain" and "knee pain exercises" are counted separately; no fuzzy or semantic matching.
- **Migration is delete-only** -- old `chat_topics` entries are dropped, not migrated into `recent_conversations`, so historical context from before the redesign is lost.

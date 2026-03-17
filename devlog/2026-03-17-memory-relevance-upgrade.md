# Memory System Relevance Upgrade
**Date**: 2026-03-17  |  **Status**: Completed

## What Was Built
Long-term memory entries now carry a relevance score combining 30-day half-life temporal decay, an access-frequency boost, and an evergreen override flag. Each entry also stores an optional `context` string that explains *why* the memory matters, surfaced in the system-prompt summary. Short-term entries that repeat at or above a configurable threshold are auto-promoted to long-term memory. Legacy entries are backfilled with the new fields on load, so the upgrade is fully backward-compatible. Inspired by OpenClaw (decay + promotion) and Claude Code (context/why pattern).

## Architecture
`_relevance_score` computes `decay + access_boost` per entry: exponential decay over age in days (half-life 30 d), overridden to 1.0 for evergreen entries, plus `0.2 * log1p(access_count)`. `get_summary` sorts long-term entries by this score, selects the top N, and increments their `access_count` -- creating a feedback loop where frequently surfaced memories stay relevant. Before scoring, `_promote` scans short-term categories for any value appearing >= `PROMOTION_THRESHOLD` times, creates a long-term "fact" entry with an auto-generated context note, and removes the originals. `_backfill_entry` runs on every `_load`, adding `context`, `evergreen`, and `access_count` defaults to entries that lack them.

## Key Files
| File | Purpose |
|---|---|
| `functions/user_memory.py` | Core memory module: scoring, promotion, backfill, CRUD, Flask API |
| `tests/test_user_memory.py` | 81 tests covering all memory features |

## Technical Decisions
- **30-day half-life temporal decay** -- entries lose half their base score each month, keeping the summary fresh.
- **Evergreen override** -- pinned entries (e.g., birthday, allergies) bypass decay entirely (decay fixed at 1.0).
- **Key-based access tracking** -- `access_count` increments by key when an entry appears in `get_summary`, avoiding id fragility.
- **Promotion threshold of 3** -- a short-term value repeated 3+ times auto-promotes to long-term as a "fact".
- **Backward-compatible backfill on load** -- `_backfill_entry` uses `setdefault` so existing values are never overwritten.

## Usage
Store a memory with context: `mem.remember("preference", "No sugar", key="sugar", context="for meal plans", evergreen=True)`. Call `mem.get_summary()` to get a ranked, access-tracked summary ready for system-prompt injection. Promotion happens automatically during `get_summary`; no manual intervention needed.

## Testing
81 total tests (57 original + 24 new). New tests cover: context/evergreen storage, backfill defaults, relevance score math, summary ordering, access-count increment, promotion at/below threshold, deduplication, short-term cleanup after promotion, and API validation for the new fields.

## Known Limitations
- Scoring is purely temporal + access-based; no semantic similarity or embedding-based retrieval.
- Promotion only checks exact value matches; near-duplicates (e.g., "/Dashboard" vs "/dashboard") are not merged.
- `access_count` only increments via `get_summary`; direct `get_all` calls do not affect ranking.
- No cap on long-term entry count; a very active user could accumulate unbounded entries.

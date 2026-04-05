# Heartbeat: Proactive Agent Wake System

**Date**: 2026-03-25  |  **Status**: Completed (v2 - improved decision-making)

## What Was Built

A heartbeat system inspired by OpenClaw that enables DREAM-Chat to proactively reach out to users with timely, relevant information. Every 30 minutes during configurable active hours (default 8 AM - 10 PM), a lightweight LLM triage call evaluates rich user context and decides whether to send a proactive message or stay silent.

**v2 improvements:** Research-backed four-gate decision framework (Relevance -> Information Value -> Timing -> Confidence), enriched context assembly pulling health trends, workout plans, nutrition goals, and last user activity. Time-of-day awareness guides message type selection. Anti-pattern protections (no guilt, no spam, no stale info).

## Architecture

```
_scheduler_loop (30s tick)
  -> run_heartbeat()
     -> _should_run() gate checks (enabled, active hours, interval)
     -> _build_context() assembles:
        - Time window awareness (morning/midday/evening)
        - User memory (goals, preferences, health facts)
        - Pending reminders (next 4 hours)
        - Calendar events (next 4 hours)
        - Health data trends (7-day HR, BP, HRV, steps)
        - Active workout plan + today's schedule + completion status
        - Nutrition goals & dietary preferences
        - Last user activity (to avoid interrupting active users)
        - De-dup awareness (topics already messaged today)
     -> _call_llm() lightweight triage (gpt-4o-mini)
     -> _deliver_message() via WhatsApp queue or web chat
```

## Key Files

| File | Purpose |
|------|---------|
| `functions/heartbeat.py` | Core heartbeat runner with rich context assembly |
| `skills/heartbeat.md` | Four-gate decision framework for LLM triage |
| `config/heartbeat_config.json` | User-configurable settings |
| `functions/cron_jobs.py` | Hooks heartbeat into scheduler + API routes |
| `templates/settings_heartbeat.html` | Settings UI |
| `static/settings_heartbeat.js` | Frontend JS |
| `tests/test_heartbeat.py` | 45 unit/integration tests |

## Technical Decisions

- **Four-gate decision model** (from CHI 2025 research): Relevance -> Information Value -> Timing -> Confidence. Each gate can suppress independently.
- **Time-of-day awareness:** Morning messages are gentle previews; midday messages are practical nudges; evening messages celebrate progress.
- **"Would they thank me?" test:** The single most effective heuristic from notification UX research.
- **Never guilt or shame:** Research shows guilt-based messaging drives disengagement. Always positive framing.
- **Accumulate evidence before speaking:** Require 3+ data points before flagging health trends, avoiding false alarms from single readings.
- **Last user activity check:** If user was active <30 min ago, the LLM is told to be cautious about interrupting.

## Testing

```bash
python3 -m pytest tests/test_heartbeat.py -v
```

45 tests covering: time windows, health trend extraction, workout context, nutrition context, user activity detection, decision quality checks on instructions.

## Known Limitations

- Single-user only (matches DREAM-Chat's current architecture)
- Heartbeat cannot trigger tool calls (observe-only, no side effects)
- No conversation threading: heartbeat messages are one-shot outbound
- Health data depends on having Apple Health exports processed

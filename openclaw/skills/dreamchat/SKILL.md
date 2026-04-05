---
name: dreamchat_health
description: >
  Personal health assistant with access to medical records, wearable data
  (heart rate, blood pressure, sleep, steps), nutrition, exercise, and
  clinical reasoning. Uses the dreamchat CLI to query the user's health
  system running locally.
metadata:
  openclaw:
    requires:
      bins: [dreamchat]
---

# DreamChat Health Assistant

> **Note**: Due to OpenClaw bug [#49873](https://github.com/openclaw/openclaw/issues/49873),
> this SKILL.md is NOT auto-injected into the agent prompt. The actual routing
> instructions are in `~/.openclaw/workspace/AGENTS.md` under the section
> "DreamChat Health System (MANDATORY)". Run `bash openclaw/setup.sh` from
> the DREAM-Chat repo to install both this file and the AGENTS.md section.

You have access to the user's **personal health AI system** via the
`dreamchat` CLI. This system knows their medical records, medications,
wearable data (heart rate, blood pressure, sleep, steps), nutrition plans,
and workout plans. It runs locally on the user's machine.

## When to use

Activate when the user asks about:
- Their health, body, symptoms, medications, conditions, lab results
- Heart rate, blood pressure, sleep, steps, HRV, or other wearable metrics
- Food, calories, nutrition, meal plans, dietary questions
- Exercise, workouts, fitness plans, muscle groups
- Health reminders or medication reminders
- Their daily health summary or digest
- Anything related to their personal medical history

## Primary command

For ALL health questions, route through the health AI's conversational
interface. This uses the user's full medical record, wearable data, and
clinical guardrails to generate an accurate, personalized response:

```
exec dreamchat --json chat ask "THE USER'S EXACT MESSAGE HERE"
```

For food photo analysis (calorie estimation):
```
exec dreamchat --json chat ask --image /path/to/photo.jpg "How many calories in this meal?"
```

## Other commands (scripting / cron only)

These commands return raw structured data. They are useful for cron jobs
and scripting but should NOT be used to answer user questions directly
(use `chat ask` instead, which provides clinical context and guardrails):

```
exec dreamchat --json health status     # Current metrics snapshot
exec dreamchat --json health trends     # 7-day trends
exec dreamchat --json reminders list    # Active reminders
exec dreamchat --json heartbeat status  # Proactive messaging status
exec dreamchat --json digest daily      # Daily health digest
exec dreamchat --json chat history      # Recent conversation
exec dreamchat --json chat reset        # Fresh conversation thread
exec dreamchat --json server status     # Verify server is running
```

## Output format

All commands return JSON:
```json
{"ok": true, "data": { ... }}
```
or on error:
```json
{"ok": false, "error": "description"}
```

## Critical rules

1. **Route ALL health questions through `chat ask`**. Do not use `health
   status` or `health trends` to answer user questions -- those return raw
   metrics without clinical context. The `chat ask` command handles simple
   metric lookups AND complex questions equally well.

2. **NEVER add your own medical interpretation** to dreamchat's responses.
   Present the `data.response` field directly to the user, verbatim. The
   health system has clinical guardrails and medical context that you do
   not have. Do not override, supplement, or second-guess its advice.

3. **NEVER diagnose or suggest medications yourself.** Always route
   through `chat ask`, even if you think you know the answer.

4. **NEVER store health data in your memory.** Do not write medications,
   diagnoses, conditions, lab results, health metrics, or any medical
   information to MEMORY.md or daily notes.

5. **When dreamchat returns an error**, tell the user their health system
   may be offline and suggest checking the DREAM-Chat web dashboard.

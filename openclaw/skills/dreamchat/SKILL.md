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

## Commands

### Factual health data (fast, no AI reasoning needed)

Current health metrics snapshot:
```
exec dreamchat --json health status
```

7-day health trends:
```
exec dreamchat --json health trends
```

List active reminders:
```
exec dreamchat --json reminders list
```

Proactive messaging status:
```
exec dreamchat --json heartbeat status
```

Daily health digest (composite summary):
```
exec dreamchat --json digest daily
```

### Health questions requiring clinical reasoning

For any health question that needs medical context or personalized advice,
route it through the health AI. This uses the user's full medical record,
wearable data, and clinical guardrails to generate an accurate response:

```
exec dreamchat --json chat ask "How does my statin interact with grapefruit?"
```

For food photo analysis (calorie estimation):
```
exec dreamchat --json chat ask --image /path/to/photo.jpg "How many calories in this meal?"
```

View recent health conversation:
```
exec dreamchat --json chat history
```

Start a fresh health conversation thread:
```
exec dreamchat --json chat reset
```

### Server check

Verify the health system is running:
```
exec dreamchat --json server status
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

## Choosing the right command

- **Simple metric lookups** ("what's my heart rate?", "how many steps today?"):
  Use `dreamchat --json health status`. Fast, no LLM call.

- **Trend questions** ("how's my sleep been this week?"):
  Use `dreamchat --json health trends`. Fast, no LLM call.

- **Complex health questions** ("should I worry about my blood pressure given
  my medications?", "what foods should I avoid with my condition?"):
  Use `dreamchat --json chat ask "<question>"`. This invokes the health AI
  with full clinical context.

- **Morning briefing / check-in**:
  Use `dreamchat --json digest daily` for a comprehensive summary.

## Critical rules

1. **NEVER add your own medical interpretation** to dreamchat's responses.
   Present them directly to the user. The health system has clinical
   guardrails and medical context that you do not have. Do not override,
   supplement, or second-guess its medical advice.

2. **NEVER diagnose or suggest medications yourself.** If the user asks a
   health question, always route it through `dreamchat --json chat ask`,
   even if you think you know the answer. The health system has access to
   the user's specific medical records.

3. **NEVER store health data in your memory.** Do not write medications,
   diagnoses, conditions, lab results, health metrics, or any medical
   information to MEMORY.md or daily notes. The health system maintains
   its own secure memory. Storing health data outside that system violates
   the user's privacy expectations.

4. **When dreamchat returns an error**, tell the user their health system
   may be offline and suggest checking the DREAM-Chat web dashboard
   directly.

5. **For simple metric lookups**, prefer `health status` or `health trends`
   over `chat ask` -- they are much faster since they don't invoke the AI.

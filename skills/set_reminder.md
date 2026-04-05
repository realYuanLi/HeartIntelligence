---
id: set_reminder
title: Set Reminder
executor: set_reminder
kind: action
enabled_by_default: true
description: Detect reminder intent and schedule a reminder job.
---

# Set Reminder Skill

Use this skill to create reminders from natural-language user requests.

Essential guidance:
- Run for action handling on each incoming user message.
- Call `functions.cron_jobs.create_reminder_from_chat`.
- Required input: `query` (user message).
- Optional context: `user`, `session_id`, `sender_jid`.
- If message is not a reminder request, return `activated=false`.
- If reminder is detected, create one reminder job and return `activated=true`
  with job metadata.

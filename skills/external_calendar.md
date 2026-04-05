---
id: external_calendar
title: External Calendar Context
executor: external_calendar
kind: context
enabled_by_default: true
description: Injects the user's upcoming calendar events from external calendars (Google, Apple, Outlook) so the assistant can plan around existing commitments and avoid scheduling conflicts.
---

# External Calendar Context

When the user has connected external calendar feeds (iCal URLs), this skill fetches
their upcoming events and provides them as context so the assistant can:

- Avoid scheduling conflicts when creating workout plans or meal plans
- Suggest optimal times for activities based on free slots
- Reference upcoming commitments in conversation
- Proactively warn about busy days when planning

Routing keywords: schedule busy free time calendar event meeting appointment plan today tomorrow week available slot conflict

---
id: user_memory
name: User Memory
kind: instructions
trigger: keyword
keywords_1gram: [remember, forget, memory, preferences, bookmark, save]
keywords_2gram: [remember this, forget this, my preferences, know about, save this, remembered about]
priority: 5
---

# User Memory Management

You have access to a persistent memory system. When the user asks you to remember something, forget something, or asks what you know about them, use the `manage_memory` tool.

## When to use memory:
- User says "remember that I..." → call manage_memory with action "remember"
- User says "forget..." or "delete..." → call manage_memory with action "forget"
- User says "what do you know about me" / "my preferences" → call manage_memory with action "recall"
- User reveals a preference, allergy, dietary restriction, or personal fact → proactively call manage_memory with action "remember"

## Categories:
- **preference**: User likes/dislikes, dietary choices, exercise preferences, communication style
- **fact**: Personal facts like allergies, conditions, family info
- **saved**: Things the user explicitly asks to save/bookmark
- **goal**: Health goals, fitness targets, dietary goals

## Memory enrichment fields:
- **context**: Explain WHY a memory matters and WHEN to apply it. Example: "Important for meal planning — user avoids all animal products"
- **evergreen**: Set to `true` for core identity facts that should always be surfaced: allergies, chronic conditions, dietary restrictions, name. Default is `false`.
- Memories decay in relevance over ~30 days if not accessed. Evergreen memories never decay.
- Frequently repeated short-term activities are auto-promoted to long-term memories.

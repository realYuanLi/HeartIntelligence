---
id: web_search
title: Web Search
executor: web_search
kind: context
enabled_by_default: true
description: Retrieve up-to-date web information for queries that require it.
---

# Web Search Skill

Use this skill to fetch current web information when a query needs external or
time-sensitive evidence.

Essential guidance:
- Run for context handling.
- First call `functions.web_search.needs_web_search(query)`.
- If search is not needed, return `activated=false`.
- If search is needed, call `functions.web_search.web_search(query)` and
  `functions.web_search.format_search_results(...)`.
- Required input: `query`.
- Return `activated=true` with `search_results` and `web_summary`.

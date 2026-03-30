# OpenClaw Integration Architecture
**Date**: 2026-03-30  |  **Status**: Design finalized, Phase 1 implemented

## Design Decision

DREAM-Chat connects to the OpenClaw ecosystem as a **health domain provider**, following the Dr. Claw integration pattern: a thin CLI as the stable contract, with OpenClaw acting as a multi-channel secretary.

Three integration approaches were evaluated:

| Approach | Effort | DREAM-Chat changes | Standalone value |
|----------|--------|---------------------|------------------|
| **CLI + Skill** (chosen) | Low | Zero | Yes |
| MCP Server | Medium | Zero | No |
| OpenClaw Plugin | High | Zero | No |

The CLI wins because it's the thinnest bridge, requires zero existing code changes, and is independently useful for scripting/debugging even without OpenClaw.

## Ecosystem Context

Research into three projects informed the design:

**Dr. Claw** (OpenLAIR) — Research-focused agentic IDE. Its OpenClaw integration is deliberately shallow: OpenClaw calls `drclaw --json <command>` via shell exec. Dr. Claw owns execution, OpenClaw is the secretary. Key lesson: **keep the integration surface shallow for reliability**.

**AutoClaw** (Zhipu AI) — Desktop wrapper around OpenClaw. Doesn't modify OpenClaw — wraps it with a pre-configured model + browser automation. Key lesson: **you don't need to be part of OpenClaw to be in the ecosystem; expose a clean interface it can consume**.

**DREAM-Chat's position**: The health domain provider. OpenClaw is the universal interface layer that routes to domain specialists.

| Provider | Domain | Interface |
|----------|--------|-----------|
| Dr. Claw | Research | `drclaw` CLI |
| AutoClaw | General productivity | Wrapped OpenClaw |
| **DREAM-Chat** | **Personal health** | **`dreamchat` CLI** |

## Ownership Boundaries

| Concern | Owner |
|---------|-------|
| Messaging channels (WhatsApp, Telegram, Discord, etc.) | OpenClaw |
| Health reasoning, EHR, wearables, imaging | DREAM-Chat |
| Clinical guardrails (`boundaries.md`, `soul.md`) | DREAM-Chat |
| User-facing personality on chat | OpenClaw (secretary tone) |
| Health domain personality | DREAM-Chat (warm companion) |
| Memory (general) | OpenClaw |
| Memory (health) | DREAM-Chat |
| Model selection for health queries | DREAM-Chat (GPT-4o) |
| Model selection for general queries | OpenClaw |

## Coexistence Model

Both standalone and OpenClaw modes run simultaneously. The Flask backend doesn't care which door a message enters through — all paths hit the same API.

```
┌──────────────────────────────────────────────┐
│              DREAM-Chat Flask                 │
│   (EHR · skills · LLM · guardrails · all)    │
│         /api/message    /api/whatsapp/message │
│              ▲                ▲                │
└──────────────┼────────────────┼───────────────┘
               │                │
     ┌─────────┼────────┐      │
     │         │        │      │
  Web UI    dreamchat   │   Baileys
  (browser) CLI (new)   │   Bridge
     │         │        │   (existing)
     ▼         ▼        │      ▼
  Standalone  OpenClaw  │   Standalone
  user        user      │   WhatsApp user
```

**Three user patterns, no conflicts:**

1. **Different users, different paths** — User A uses standalone WhatsApp, User B uses OpenClaw. No conflict.
2. **Same user, channel split** — WhatsApp stays on DREAM-Chat directly (fast, one hop). Telegram/Discord/Voice go through OpenClaw → CLI → Flask. Best UX.
3. **Full migration** — User unlinks WhatsApp from DREAM-Chat, lets OpenClaw own all channels. Still uses web dashboard for visual features (3D body viewer, etc.).

WhatsApp cannot be linked to both simultaneously (dual-response problem). The recommended pattern is #2: let DREAM-Chat keep WhatsApp, add OpenClaw for new channels.

## Data Flow: CLI as Privacy Boundary

The CLI controls exactly what data crosses from DREAM-Chat to OpenClaw:

**Structured data commands** (no LLM, fast):
```
dreamchat --json health status  → aggregated metrics only (HR, BP, steps)
dreamchat --json health trends  → 7-day trend summaries
dreamchat --json reminders list → reminder schedule info
dreamchat --json digest daily   → composite health summary
```

**Conversational commands** (routes to DREAM-Chat's LLM):
```
dreamchat --json chat ask "question"
  → CLI sends question to Flask
  → Flask loads full EHR + mobile data INTERNALLY
  → GPT-4o reasons with full context INTERNALLY
  → Flask returns the curated LLM response
  → CLI returns response to OpenClaw
```

OpenClaw sees the **answer**, never the raw EHR. The full `patient.json` with diagnoses, medication dosages, allergies — that never leaves DREAM-Chat's process.

**Deliberately omitted:** `health patient` command. Raw patient data stays inside DREAM-Chat. Health questions go through `chat ask` which applies clinical guardrails before responding.

## Privacy Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Dual-LLM exposure (health data → OpenClaw's LLM) | Medium | CLI returns curated answers, not raw EHR. Recommend local LLM for OpenClaw. |
| OpenClaw memory storing health facts | Medium-High | SKILL.md rule: "NEVER store health data in your memory" |
| Third-party OpenClaw skills accessing health context | Low-Medium | General OpenClaw risk, not specific to integration |
| Raw EHR data leaking | Low | No CLI command exposes raw patient.json |
| Medical imaging data leaking | None | No CLI command exposes NIfTI files |

## Proactive Messages: Pull vs Push

**Phase 1 (implemented):** Pull-based. OpenClaw's cron runs `dreamchat --json digest daily` periodically. Simpler than DREAM-Chat's 4-gate heartbeat but requires zero changes.

**Phase 2 (planned):** Push-based. Add `delivery_method: "file"` to heartbeat config. Heartbeat writes proactive messages to `~/.dreamchat/outbound.json`. CLI polls with `dreamchat --json outbound pending`. OpenClaw delivers through user's preferred channel. This gives OpenClaw users the full intelligent heartbeat.

## Phasing

| Phase | What | Status |
|-------|------|--------|
| 1 | CLI + Skill + tests (all structured data commands + `chat ask`) | Done |
| 2 | `chat ask --image`, file-based heartbeat delivery, OpenClaw cron template | Planned |
| 3 | MCP server for richer tool integration, shared memory bridge | Future |

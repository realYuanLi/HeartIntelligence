# Implementation Log: MCP Server for Direct Health Integration (2026-04-02)

## What Changed
Instead of OpenClaw's agent running shell `exec dreamchat --json chat ask "..."` (fragile, needs approval, requires JSON parsing), DREAM-Chat now exposes itself as an MCP server with structured tools.

## New Files
- `dreamchat/mcp_server.py`: FastMCP server exposing `health_ask` and `health_status` tools
- `scripts/dreamchat-mcp`: Entry point script for the MCP server

## Modified Files
- `openclaw/setup.sh`: Now registers MCP server via `openclaw mcp set` (6 steps total)
- `openclaw/agents-section.md`: Updated to use MCP tool as primary, exec as fallback
- `tests/test_dreamchat_cli.py`: Added 9 MCP tests (103 total, all pass)

## How It Works
1. `setup.sh` registers `dreamchat-health` MCP server with OpenClaw
2. OpenClaw spawns the MCP server on demand (stdio transport)
3. Agent sees `health_ask(question)` as a structured tool in its tool list
4. Agent calls tool directly — no shell exec, no approval, no JSON parsing
5. MCP server routes through DreamChatClient → Flask API → LLM response
6. Response returned to agent as structured text

## Status: Complete
103/103 tests pass. Devlog: devlog/2026-04-02-mcp-server.md

---

# Implementation Log: OpenClaw Routing Hardening (2026-04-02)

## Bugs Fixed
1. CLI `main()` didn't catch `SystemExit` from `_login()` in JSON mode -> tracebacks instead of JSON
2. `setup.sh` didn't inject AGENTS.md section -> fresh installs had no routing instructions
3. SKILL.md decision tree caused agent to use `health status`/`digest daily` -> raw JSON to users

## Files Changed
- `dreamchat/client.py`: Added `DreamChatError`, replaced `SystemExit` in `_login()`
- `dreamchat/cli.py`: Wrapped dispatch in try/except for `DreamChatError` + `Exception`
- `openclaw/agents-section.md`: NEW - canonical AGENTS.md section (source of truth)
- `openclaw/setup.sh`: Added step 3/4 to inject/update AGENTS.md section (idempotent)
- `openclaw/skills/dreamchat/SKILL.md`: Added bug notice, removed decision tree, all -> `chat ask`
- `tests/test_dreamchat_cli.py`: 10 new tests (94 total, all pass)
- `~/.openclaw/workspace/AGENTS.md`: Updated live with error handling + verbatim rules

## Status: Complete
94/94 tests pass. Devlog: devlog/2026-04-02-openclaw-routing-hardening.md

---

# Implementation Log: dreamchat CLI + OpenClaw Integration

## Phase 1: Product Design - COMPLETE
Spec: 84 tests covering client, CLI, SKILL.md. pytest + unittest.mock. Zero new deps.

## Phase 2: Code & Review - COMPLETE (Round 1, Approved)
- Coder wrote tests/test_dreamchat_cli.py (84 tests)
- Reviewer approved with 2 minor fixes (silent assertion, imports)
- Minor fixes applied, all 84 tests pass

## Phase 3: Test - COMPLETE
Tests ARE the deliverable. 84/84 pass in 0.76s.

## Phase 4: Dev Log - COMPLETE
Written to devlog/2026-03-30-dreamchat-cli-openclaw.md

## Phase 5: Git - COMPLETE
Commit: 81ecfd9 feat(openclaw): add dreamchat CLI and OpenClaw skill integration
Branch: feat/multi-user-whatsapp
8 files, 2037 insertions, 0 deletions

---

## 2026-04-05: Sidebar White Crystal Redesign
- Phase 1 (Design): Spec created — white backgrounds, structural demarcation, neutral interactive states
- Phase 2 (Code + Review): Round 1 coded, reviewer found 5 issues in recent-item/dropdown styles. Round 2 fixed all. Approved.
- Phase 3 (Test): Skipped — CSS-only visual change, no testable logic
- Phase 4 (Log): devlog/2026-04-05-sidebar-white-crystal.md
- Phase 5 (Git): CSS changes ready for commit

---

## 2026-04-05: Sidebar Simplification
- Phase 1 (Design): Spec for black brand text, hex colors, system fonts, stripped decorations
- Phase 2 (Code + Review): Round 1 coded, reviewer found 3 issues (leftover DM Sans, rgba colors, reduced-motion). Round 2 fixed all. Clean.
- Phase 3 (Test): Skipped — CSS-only visual change
- Phase 4 (Log): devlog/2026-04-05-sidebar-simplify.md

---

## 2026-04-05: Fix dual input box bug
- Root cause: `main` has `display: flex` in author CSS, which overrides the `[hidden]` attribute's UA stylesheet `display: none`. So `main.hidden = true` was a no-op — main stayed visible when inline panels opened, showing two input boxes.
- Fix: Added `main[hidden], .input-container[hidden], .inline-panel[hidden] { display: none !important; }` to style.css.
- 1 line of CSS. Affects: style.css only.

---

## 2026-04-05: Match inline panel inputs to chat page
- Added mic button, attach button, file input, and image preview to Exercise/Nutrition inline panels in base.html
- Uses class-based selectors (.inline-mic-btn, .inline-attach-btn, etc.) to avoid ID conflicts with welcome/chat page elements
- Added inline-specific image upload handling in script.js: file picker wiring, pendingImages array, preview rendering, sessionStorage handoff on send
- Mic button is visual-only (functional mic requires being in a chat session); attach + send are fully wired

---

## 2026-04-05: Fix inline panel input box width/position
- Inline panel inputs inherited `.welcome-container .input-container` styles (min-width 700px, max-width 1000px, centered in flow) instead of matching the chat page fixed input
- Added CSS overrides for `.inline-panel .input-container` to match `.input-container.fixed`: position fixed at bottom, left: 400px, max-width 850px, with ::before background extension
- Added `.inline-panel .welcome-container { padding-bottom: 6rem }` for fixed input clearance
- CSS-only fix in style.css

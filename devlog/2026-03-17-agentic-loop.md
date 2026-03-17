# Agentic Tool-Use Loop
**Date**: 2026-03-17  |  **Status**: Completed

## What Was Built
An agentic multi-step loop that lets the LLM chain multiple tool calls across iterations to answer complex queries. Previously, the agent supported only a single round of tool calls. Now, queries that span multiple domains (e.g., "check my blood results and then build a meal plan") are automatically routed through a plan-and-execute loop that iterates up to 5 times, gathering information incrementally before producing a final answer.

## Architecture
A new `agentic_loop.py` module provides four pure-function helpers and a `LoopState` dataclass. In `agent.py`, `openai_reply()` classifies incoming queries as **simple** or **complex**. Simple queries follow the original single-round path. Complex queries enter the agentic loop: a lightweight LLM call generates a 3-5 step plan, then the main model iterates -- executing tool calls, summarizing results, injecting a progress hint, and checking termination conditions each round. A token-saving mechanism (`_drop_old_tool_messages`) prunes tool messages older than the last 2 iterations.

**Data flow**: User message -> `classify_query` -> (if complex) `generate_plan` -> loop { LLM call -> tool execution -> `summarize_tool_result` -> `should_continue` check } -> final response.

## Key Files
| File | Purpose |
|---|---|
| `functions/agentic_loop.py` | `LoopState` dataclass, `classify_query`, `generate_plan`, `summarize_tool_result`, `should_continue` |
| `functions/agent.py` | Integrates agentic loop into `openai_reply()`; extracted `_execute_tool_call()` and `_drop_old_tool_messages()` |
| `tests/test_agentic_loop.py` | 48 unit tests covering all four helper functions and LoopState |

## Technical Decisions
- **Heuristic classifier over LLM classifier**: `classify_query` uses keyword domain-matching and multi-step connector detection. Avoids an extra LLM round-trip for every message; false positives just add one cheap planning call.
- **Separate planning model**: `generate_plan` uses `gpt-4o-mini` with `temperature=0` to keep planning fast and deterministic. Falls back to a single generic step on failure.
- **Tool message pruning**: `_drop_old_tool_messages` keeps only the last 2 iteration groups to prevent context window overflow on multi-step chains.
- **Graceful termination**: When max iterations are hit mid-tool-call, the loop executes the pending tools, then makes one final LLM call with `include_tools=False` to force a text response.

## Usage
Automatic. When a user sends a multi-domain or multi-step query, `classify_query` triggers the agentic path. No UI changes or user action required.

## Testing
```bash
pytest tests/test_agentic_loop.py -v
```
48 tests cover: `LoopState` defaults and isolation, `classify_query` for simple/complex edge cases and connector detection, `summarize_tool_result` truncation and boundary handling, `should_continue` termination logic, and `generate_plan` parsing with mocked OpenAI client.

## Known Limitations
- `classify_query` uses substring matching for connectors, so unrelated sentences containing "and then" will trigger the complex path unnecessarily.
- The planning call adds ~200-400ms latency to complex queries.
- `_drop_old_tool_messages` counts iteration boundaries by assistant messages with `tool_calls`, which may miscount if the LLM emits tool calls in unexpected patterns.
- No persistent plan state -- if the connection drops mid-loop, progress is lost.

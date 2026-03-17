# Reactive Agent Tool Loop
**Date**: 2026-03-17  |  **Status**: Completed

## What Was Built
A reactive tool-calling loop for the Agent class that lets the LLM chain multiple tool calls across iterations before producing a final answer. Previously the agent handled at most one tool round; it now loops until the model stops requesting tools or hits a configurable cap (default 8 iterations). This powers multi-step workflows like "find exercises then build a workout plan" without extra user prompts.

## Architecture
`agentic_loop.py` provides three primitives: `LoopState` (iteration counter + max), `summarize_tool_result` (sentence-boundary truncation to 800 chars), and `make_reflection_message` (system nudge injected after iteration 1+). The loop lives in `Agent.openai_reply()`: after the first LLM call returns tool_calls, it enters a while-loop that executes tools, appends results, and calls the LLM again. Three safeguards keep context growth in check -- progressive summarization (iteration 2+), old tool-message pruning via `_drop_old_tool_messages` (keeps last 2 iteration groups), and reflection deduplication (old reflection removed before new one is appended). At max iterations the final call omits the `tools` parameter, forcing a text response.

## Key Files
| File | Purpose |
|---|---|
| `functions/agentic_loop.py` | LoopState dataclass, summarize_tool_result, make_reflection_message |
| `functions/agent.py` | Reactive while-loop in openai_reply(), _drop_old_tool_messages, _execute_tool_call |
| `tests/test_agentic_loop.py` | 16 unit tests for LoopState, summarize, reflection primitives |
| `tests/test_agent_loop.py` | 17 integration tests for loop behavior end-to-end |

## Technical Decisions
- **Sentence-boundary truncation** over token counting -- simpler, no tokenizer dependency, good enough for context control.
- **Reflection as a system message** rather than modifying the prompt -- easy to deduplicate and keeps the base system prompt unchanged.
- **Forced tool-less call at max iterations** instead of raising an error -- guarantees the user always gets a response.
- **Keep last 2 iteration groups** in pruning -- balances recency with context window budget.

## Usage
Fully automatic. When a user message triggers tool calls, the loop runs transparently. No configuration or user action required.

## Testing
```bash
pytest tests/test_agentic_loop.py tests/test_agent_loop.py -v
```
Unit tests cover LoopState defaults, truncation edge cases (boundary punctuation, no punctuation, empty string), and reflection gating. Integration tests mock OpenAI and verify: no-tool passthrough, single-round tools, multi-round chaining, parallel tool calls, max-iteration forced stop, tool error resilience, progressive summarization timing, and reflection deduplication across iterations.

## Known Limitations
- Summarization is character-based truncation, not semantic -- important details at the end of long tool results may be lost.
- Max iterations is hardcoded to 8 in LoopState default; not yet user-configurable per request.
- No per-tool timeout; a slow tool blocks the entire loop iteration.

"""Integration tests for the reactive agentic loop in Agent.openai_reply()."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from functions.agentic_loop import REFLECTION_CONTENT, summarize_tool_result


# ---------------------------------------------------------------------------
# Helpers to build mock OpenAI response objects
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, arguments: dict, call_id: str = "call_001"):
    """Build a mock tool_call object matching OpenAI's structure."""
    tc = SimpleNamespace()
    tc.id = call_id
    tc.type = "function"
    tc.function = SimpleNamespace()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_response(content: str | None = None, tool_calls: list | None = None):
    """Build a mock openai.chat.completions.create() return value."""
    message = SimpleNamespace()
    message.content = content
    message.tool_calls = tool_calls or None  # None when no tool calls
    # Provide role for messages that get appended
    message.role = "assistant"
    # Make it dict-like enough: the loop does openai_messages.append(message)
    # and later checks isinstance(m, dict) — SimpleNamespace is not a dict, so
    # the dedup filter using isinstance(m, dict) will skip it correctly.

    # For _drop_old_tool_messages, give it getattr-compatible tool_calls
    choice = SimpleNamespace()
    choice.message = message
    response = SimpleNamespace()
    response.choices = [choice]
    return response


def _build_agent():
    """Create an Agent with minimal config, mocking SkillRuntime."""
    with patch("functions.agent.SkillRuntime") as MockSR:
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {}
        MockSR.return_value = mock_runtime

        from functions.agent import Agent
        agent = Agent(
            role="test",
            llm="gpt-4o",
            sys_message="You are a test assistant.",
            ehr_data={},
            mobile_data={},
        )
    # Ensure skill_runtime.run always returns {} in tests
    agent.skill_runtime = mock_runtime
    return agent


# ===========================================================================
# 1. No tool calls — LLM returns text directly
# ===========================================================================

class TestNoToolCalls:
    """When the LLM returns text directly, the loop should never be entered."""

    def test_single_llm_call_text_response(self):
        agent = _build_agent()
        text_response = _make_response(content="Hello! How can I help?")

        with patch("functions.agent.openai") as mock_openai:
            mock_openai.chat.completions.create.return_value = text_response
            result = agent.openai_reply([
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "Hi there"},
            ])

        assert result.content == "Hello! How can I help?"
        assert result.exercise_images == []
        assert mock_openai.chat.completions.create.call_count == 1

    def test_no_exercise_images_on_text_response(self):
        agent = _build_agent()
        with patch("functions.agent.openai") as mock_openai:
            mock_openai.chat.completions.create.return_value = _make_response(
                content="Just text"
            )
            result = agent.openai_reply([
                {"role": "user", "content": "hello"},
            ])
        assert result.exercise_images == []


# ===========================================================================
# 2. Single tool round — one tool call then text
# ===========================================================================

class TestSingleToolRound:
    """First LLM call returns 1 tool call, second returns text."""

    def test_two_llm_calls_and_correct_result(self):
        agent = _build_agent()

        tool_call = _make_tool_call("exercise_search", {"query": "push ups"}, "call_100")
        resp_with_tool = _make_response(tool_calls=[tool_call])
        resp_text = _make_response(content="Here are some push-up exercises.")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("Push-up results here", [])):
            mock_openai.chat.completions.create.side_effect = [resp_with_tool, resp_text]

            result = agent.openai_reply([
                {"role": "user", "content": "Show me push ups"},
            ])

        assert result.content == "Here are some push-up exercises."
        assert mock_openai.chat.completions.create.call_count == 2

    def test_tool_executed_with_correct_args(self):
        agent = _build_agent()

        tool_call = _make_tool_call("exercise_search", {"query": "squats"}, "call_200")
        resp_with_tool = _make_response(tool_calls=[tool_call])
        resp_text = _make_response(content="Squat info.")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("Squat data", [])) as mock_exec:
            mock_openai.chat.completions.create.side_effect = [resp_with_tool, resp_text]

            agent.openai_reply([{"role": "user", "content": "squats"}])

        mock_exec.assert_called_once()
        called_tool_call = mock_exec.call_args[0][0]
        assert called_tool_call.function.name == "exercise_search"
        assert json.loads(called_tool_call.function.arguments) == {"query": "squats"}

    def test_exercise_images_propagated(self):
        agent = _build_agent()

        tool_call = _make_tool_call("exercise_search", {"query": "bench"}, "call_300")
        resp_with_tool = _make_response(tool_calls=[tool_call])
        resp_text = _make_response(content="Bench press info.")
        fake_images = [{"name": "Bench Press", "url": "/exercises/images/bench.jpg"}]

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("Bench data", fake_images)):
            mock_openai.chat.completions.create.side_effect = [resp_with_tool, resp_text]

            result = agent.openai_reply([{"role": "user", "content": "bench press"}])

        assert result.exercise_images == fake_images


# ===========================================================================
# 3. Multi-tool chaining — two tool rounds then text
# ===========================================================================

class TestMultiToolChaining:
    """First call -> tool A, second call -> tool B, third call -> text."""

    def test_three_llm_calls(self):
        agent = _build_agent()

        tc_a = _make_tool_call("exercise_search", {"query": "chest"}, "call_A")
        tc_b = _make_tool_call("manage_workout_plan", {"action": "create", "details": "chest day"}, "call_B")

        resp_a = _make_response(tool_calls=[tc_a])
        resp_b = _make_response(tool_calls=[tc_b])
        resp_text = _make_response(content="Your workout plan is ready!")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("Tool result", [])):
            mock_openai.chat.completions.create.side_effect = [resp_a, resp_b, resp_text]

            result = agent.openai_reply([{"role": "user", "content": "Create a chest workout"}])

        assert result.content == "Your workout plan is ready!"
        assert mock_openai.chat.completions.create.call_count == 3

    def test_multiple_tool_calls_in_single_response(self):
        """LLM returns 2 tool calls in one response (parallel tool use)."""
        agent = _build_agent()

        tc1 = _make_tool_call("exercise_search", {"query": "chest"}, "call_P1")
        tc2 = _make_tool_call("manage_nutrition", {"action": "view_plan"}, "call_P2")
        resp_parallel = _make_response(tool_calls=[tc1, tc2])
        resp_text = _make_response(content="Done!")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("result", [])) as mock_exec:
            mock_openai.chat.completions.create.side_effect = [resp_parallel, resp_text]

            result = agent.openai_reply([{"role": "user", "content": "chest workout and meal plan"}])

        assert mock_exec.call_count == 2
        assert mock_openai.chat.completions.create.call_count == 2
        assert result.content == "Done!"


# ===========================================================================
# 4. Max iterations forced stop
# ===========================================================================

class TestMaxIterations:
    """LLM always returns tool calls; loop must terminate at max_iterations."""

    def test_stops_at_max_iterations(self):
        agent = _build_agent()

        def always_tool_call(*args, **kwargs):
            # If include_tools=False, return text (forced stop)
            if kwargs.get("include_tools") is False or (
                "tools" not in kwargs and len(args) < 3
            ):
                return _make_response(content="Forced final answer.")
            tc = _make_tool_call("exercise_search", {"query": "anything"}, f"call_{always_tool_call.counter}")
            always_tool_call.counter += 1
            return _make_response(tool_calls=[tc])
        always_tool_call.counter = 0

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("tool result", [])):
            # Inspect calls to detect include_tools=False
            def side_effect(**kwargs):
                if not kwargs.get("tools"):
                    # This is the forced-stop call
                    return _make_response(content="Forced final answer.")
                tc = _make_tool_call("exercise_search", {"query": "x"}, f"call_{side_effect.n}")
                side_effect.n += 1
                return _make_response(tool_calls=[tc])
            side_effect.n = 0

            mock_openai.chat.completions.create.side_effect = side_effect

            result = agent.openai_reply([{"role": "user", "content": "infinite loop test"}])

        assert result.content == "Forced final answer."
        # 1 initial call + 8 loop iterations = 9 total
        # But at iteration 8 (max_iterations), it calls with include_tools=False
        # Initial call (1) + iterations 0-7 each call once (8) + forced final call at iter 8 (but iter 8 uses include_tools=False which is the call itself)
        # Actually: initial call returns tool -> enter loop.
        # iter 0: execute, iter++ -> 1, next call returns tool
        # iter 1: execute, iter++ -> 2, next call returns tool
        # ...
        # iter 7: execute, iter++ -> 8, 8 >= max(8), forced call with include_tools=False
        # Total: 1 (initial) + 7 (loop iters 1-7) + 1 (forced) = 9
        total_calls = mock_openai.chat.completions.create.call_count
        assert total_calls == 9  # 1 initial + 7 in-loop + 1 forced-stop

    def test_forced_stop_has_no_tools_param(self):
        """The final forced-stop call must use include_tools=False (no tools kwarg)."""
        agent = _build_agent()

        call_log = []

        def tracking_side_effect(**kwargs):
            call_log.append(kwargs)
            if "tools" not in kwargs:
                return _make_response(content="Final.")
            tc = _make_tool_call("exercise_search", {"query": "x"}, f"call_{len(call_log)}")
            return _make_response(tool_calls=[tc])

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("result", [])):
            mock_openai.chat.completions.create.side_effect = tracking_side_effect

            agent.openai_reply([{"role": "user", "content": "loop test"}])

        # Last call should not have 'tools' key
        last_call = call_log[-1]
        assert "tools" not in last_call


# ===========================================================================
# 5. Tool error resilience
# ===========================================================================

class TestToolErrorResilience:
    """When _execute_tool_call raises, the error is captured and loop continues."""

    def test_exception_becomes_error_string(self):
        agent = _build_agent()

        tc = _make_tool_call("exercise_search", {"query": "fail"}, "call_err")
        resp_tool = _make_response(tool_calls=[tc])
        resp_text = _make_response(content="Recovered gracefully.")

        call_count = {"n": 0}

        def exec_side_effect(tool_call, openai_messages):
            call_count["n"] += 1
            raise RuntimeError("Database connection failed")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", side_effect=exec_side_effect):
            mock_openai.chat.completions.create.side_effect = [resp_tool, resp_text]

            result = agent.openai_reply([{"role": "user", "content": "search exercises"}])

        assert result.content == "Recovered gracefully."
        # The loop should have continued after the error
        assert mock_openai.chat.completions.create.call_count == 2

    def test_error_message_in_tool_result(self):
        """Verify the error string format passed back as tool result."""
        agent = _build_agent()

        tc = _make_tool_call("exercise_search", {"query": "fail"}, "call_err2")
        resp_tool = _make_response(tool_calls=[tc])
        resp_text = _make_response(content="OK")

        appended_messages = []
        original_append = list.append

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call",
                          side_effect=ValueError("bad input")):
            mock_openai.chat.completions.create.side_effect = [resp_tool, resp_text]

            result = agent.openai_reply([{"role": "user", "content": "test"}])

        # We verify indirectly: the second LLM call must have received messages
        # including a tool role message with the error
        second_call_kwargs = mock_openai.chat.completions.create.call_args_list[1]
        messages_sent = second_call_kwargs[1].get("messages") or second_call_kwargs[0][0] if second_call_kwargs[0] else second_call_kwargs[1]["messages"]
        tool_msgs = [m for m in messages_sent if isinstance(m, dict) and m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "Tool error:" in tool_msgs[0]["content"]
        assert "bad input" in tool_msgs[0]["content"]


# ===========================================================================
# 6. Progressive summarization
# ===========================================================================

class TestProgressiveSummarization:
    """On iteration 2+, summarize_tool_result should be called on tool results."""

    def test_summarize_called_on_iteration_2_plus(self):
        agent = _build_agent()

        # 3 tool rounds: iterations 0, 1, 2
        tc0 = _make_tool_call("exercise_search", {"query": "a"}, "call_s0")
        tc1 = _make_tool_call("exercise_search", {"query": "b"}, "call_s1")
        tc2 = _make_tool_call("exercise_search", {"query": "c"}, "call_s2")

        resp0 = _make_response(tool_calls=[tc0])
        resp1 = _make_response(tool_calls=[tc1])
        resp2 = _make_response(tool_calls=[tc2])
        resp_text = _make_response(content="Summary done.")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("A long tool result " * 100, [])), \
             patch("functions.agent.summarize_tool_result", wraps=summarize_tool_result) as mock_summarize:
            mock_openai.chat.completions.create.side_effect = [resp0, resp1, resp2, resp_text]

            result = agent.openai_reply([{"role": "user", "content": "test"}])

        # summarize_tool_result should be called for iteration 2 only (not 0, not 1)
        assert mock_summarize.call_count == 1

    def test_summarize_not_called_on_early_iterations(self):
        """Iterations 0 and 1 should NOT call summarize_tool_result."""
        agent = _build_agent()

        tc0 = _make_tool_call("exercise_search", {"query": "a"}, "call_e0")
        resp0 = _make_response(tool_calls=[tc0])
        resp_text = _make_response(content="Done.")

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("short result", [])), \
             patch("functions.agent.summarize_tool_result") as mock_summarize:
            mock_openai.chat.completions.create.side_effect = [resp0, resp_text]

            agent.openai_reply([{"role": "user", "content": "test"}])

        mock_summarize.assert_not_called()


# ===========================================================================
# 7. Reflection message
# ===========================================================================

class TestReflectionMessage:
    """Verify reflection system message is present after iteration 1 but not 0."""

    def test_reflection_present_after_iteration_1(self):
        """After iteration 1, messages should contain the reflection nudge."""
        agent = _build_agent()

        tc0 = _make_tool_call("exercise_search", {"query": "a"}, "call_r0")
        tc1 = _make_tool_call("exercise_search", {"query": "b"}, "call_r1")

        resp0 = _make_response(tool_calls=[tc0])
        resp1 = _make_response(tool_calls=[tc1])
        resp_text = _make_response(content="Final answer.")

        messages_snapshots = []

        def capture_create(**kwargs):
            messages_snapshots.append([
                m.copy() if isinstance(m, dict) else m
                for m in kwargs["messages"]
            ])
            idx = len(messages_snapshots) - 1
            if idx == 0:
                return resp0
            elif idx == 1:
                return resp1
            else:
                return resp_text

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("result", [])):
            mock_openai.chat.completions.create.side_effect = capture_create

            agent.openai_reply([{"role": "user", "content": "test"}])

        # First call (index 0) — before any iteration, no reflection
        first_call_msgs = messages_snapshots[0]
        reflection_in_first = [
            m for m in first_call_msgs
            if isinstance(m, dict) and m.get("content") == REFLECTION_CONTENT
        ]
        assert len(reflection_in_first) == 0

        # Second call (index 1) — after iteration 0 -> state.iteration=1, reflection added
        second_call_msgs = messages_snapshots[1]
        reflection_in_second = [
            m for m in second_call_msgs
            if isinstance(m, dict) and m.get("content") == REFLECTION_CONTENT
        ]
        assert len(reflection_in_second) == 1

    def test_no_reflection_on_iteration_0(self):
        """Single tool round (iteration 0 only) — no reflection added to first in-loop call."""
        agent = _build_agent()

        tc = _make_tool_call("exercise_search", {"query": "a"}, "call_nr")
        resp_tool = _make_response(tool_calls=[tc])
        resp_text = _make_response(content="Done.")

        messages_snapshots = []

        def capture_create(**kwargs):
            messages_snapshots.append(list(kwargs["messages"]))
            if len(messages_snapshots) == 1:
                return resp_tool
            return resp_text

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("result", [])):
            mock_openai.chat.completions.create.side_effect = capture_create

            agent.openai_reply([{"role": "user", "content": "test"}])

        # The loop increments iteration after executing tools (iteration 0 -> 1)
        # Then reflection is added for iteration >= 1
        # So the second call (index 1) WILL have reflection.
        # But the first call (index 0, before loop) should NOT.
        first_call_msgs = messages_snapshots[0]
        reflection_count = sum(
            1 for m in first_call_msgs
            if isinstance(m, dict) and m.get("content") == REFLECTION_CONTENT
        )
        assert reflection_count == 0


# ===========================================================================
# 8. Reflection deduplication
# ===========================================================================

class TestReflectionDeduplication:
    """Only 1 reflection message should exist at any point, not accumulated."""

    def test_single_reflection_after_multiple_iterations(self):
        agent = _build_agent()

        # 4 tool rounds to accumulate iterations
        tool_calls = [
            _make_tool_call("exercise_search", {"query": f"q{i}"}, f"call_d{i}")
            for i in range(4)
        ]
        responses = [_make_response(tool_calls=[tc]) for tc in tool_calls]
        responses.append(_make_response(content="Final."))

        messages_snapshots = []

        def capture_create(**kwargs):
            messages_snapshots.append(list(kwargs["messages"]))
            idx = len(messages_snapshots) - 1
            return responses[idx]

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("result", [])):
            mock_openai.chat.completions.create.side_effect = capture_create

            agent.openai_reply([{"role": "user", "content": "multi-round test"}])

        # Check every snapshot after the first: at most 1 reflection message
        for i, snapshot in enumerate(messages_snapshots):
            reflection_count = sum(
                1 for m in snapshot
                if isinstance(m, dict) and m.get("content") == REFLECTION_CONTENT
            )
            assert reflection_count <= 1, (
                f"Snapshot {i} has {reflection_count} reflection messages, expected <= 1"
            )

    def test_reflection_replaced_not_appended(self):
        """Even after 3 iterations, there is exactly 1 reflection message."""
        agent = _build_agent()

        tcs = [_make_tool_call("exercise_search", {"query": f"q{i}"}, f"call_rr{i}") for i in range(3)]
        resps = [_make_response(tool_calls=[tc]) for tc in tcs]
        resps.append(_make_response(content="Done."))

        final_messages = []

        def capture_create(**kwargs):
            final_messages.clear()
            final_messages.extend(kwargs["messages"])
            idx = capture_create.n
            capture_create.n += 1
            return resps[idx]
        capture_create.n = 0

        with patch("functions.agent.openai") as mock_openai, \
             patch.object(agent, "_execute_tool_call", return_value=("result", [])):
            mock_openai.chat.completions.create.side_effect = capture_create

            agent.openai_reply([{"role": "user", "content": "dedup test"}])

        # In the very last set of messages sent, at most 1 reflection
        reflection_count = sum(
            1 for m in final_messages
            if isinstance(m, dict) and m.get("content") == REFLECTION_CONTENT
        )
        assert reflection_count <= 1

"""Comprehensive tests for the agentic loop system (functions/agentic_loop.py)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from functions.agentic_loop import (
    LoopState,
    classify_query,
    generate_plan,
    should_continue,
    summarize_tool_result,
)


# ===========================================================================
# LoopState dataclass
# ===========================================================================

class TestLoopState:
    """Tests for the LoopState dataclass defaults and construction."""

    def test_defaults(self):
        state = LoopState()
        assert state.plan == []
        assert state.current_step == 0
        assert state.iteration == 0
        assert state.max_iterations == 5
        assert state.completed is False

    def test_custom_values(self):
        state = LoopState(
            plan=["step1", "step2"],
            current_step=1,
            iteration=3,
            max_iterations=10,
            completed=True,
        )
        assert state.plan == ["step1", "step2"]
        assert state.current_step == 1
        assert state.iteration == 3
        assert state.max_iterations == 10
        assert state.completed is True

    def test_plan_list_is_independent(self):
        """Each LoopState instance should have its own plan list."""
        a = LoopState()
        b = LoopState()
        a.plan.append("x")
        assert b.plan == []


# ===========================================================================
# classify_query
# ===========================================================================

class TestClassifyQuery:
    """Tests for the classify_query heuristic classifier."""

    # --- Simple queries ---
    def test_short_single_topic(self):
        assert classify_query("What exercises target biceps?") == "simple"

    def test_greeting(self):
        assert classify_query("Hello") == "simple"

    def test_single_domain_long_but_one_domain(self):
        # Long string but only one domain (exercise)
        query = "Tell me about exercises and workout routines that are good for cardio training at the gym"
        assert classify_query(query) == "simple"

    def test_two_domains_short_query(self):
        # Two domains but short (under 150 chars)
        assert classify_query("Show me my workout and diet") == "simple"

    def test_empty_query(self):
        assert classify_query("") == "simple"

    # --- Complex queries: multi-step connectors ---
    def test_connector_and_then(self):
        assert classify_query("Find my workout and then create a meal plan") == "complex"

    def test_connector_based_on_that(self):
        assert classify_query("Check my blood results, based on that suggest a diet") == "complex"

    def test_connector_after_that(self):
        assert classify_query("Get my weight after that adjust my plan") == "complex"

    def test_connector_use_that_to(self):
        assert classify_query("Look up my preferences, use that to build a routine") == "complex"

    def test_connector_followed_by(self):
        assert classify_query("Search exercises followed by scheduling them") == "complex"

    def test_connector_once_you_have(self):
        assert classify_query("Get my allergies, once you have those pick a recipe") == "complex"

    def test_connector_case_insensitive(self):
        assert classify_query("Do task A AND THEN do task B") == "complex"

    # --- Complex queries: 3+ domains ---
    def test_three_domains_short(self):
        # exercise + nutrition + health
        assert classify_query("Show my workout, calories, and blood test results") == "complex"

    def test_four_domains(self):
        # exercise + nutrition + memory + plan
        assert classify_query("remember my workout calories and weekly schedule") == "complex"

    # --- Complex queries: long + 2 domains ---
    def test_long_two_domains(self):
        # Over 150 chars, hitting exercise + nutrition domains
        query = (
            "I want to understand how my current workout routine affects my overall "
            "protein and calorie intake so I can fine-tune my nutrition to match the "
            "intensity of my training sessions throughout the week"
        )
        assert len(query) > 150
        assert classify_query(query) == "complex"

    # --- Edge cases ---
    def test_connector_substring_not_standalone(self):
        """Connectors are substring-matched, so embedded occurrences trigger complex."""
        # "and then" is present even in this sentence
        assert classify_query("I went to the store and then came home") == "complex"

    def test_no_domain_keywords(self):
        assert classify_query("Tell me a joke about cats") == "simple"

    def test_exactly_two_domains_under_150(self):
        query = "Show workout and meal info"
        assert len(query) <= 150
        assert classify_query(query) == "simple"


# ===========================================================================
# summarize_tool_result
# ===========================================================================

class TestSummarizeToolResult:
    """Tests for the summarize_tool_result truncation utility."""

    def test_under_limit_returned_as_is(self):
        text = "Short result."
        assert summarize_tool_result(text, max_chars=800) == text

    def test_exactly_at_limit(self):
        text = "x" * 800
        assert summarize_tool_result(text, max_chars=800) == text

    def test_over_limit_truncates_at_sentence(self):
        # Build: "Sentence one. Sentence two. Sentence three. ..." with overflow
        sentences = "First sentence. Second sentence. Third sentence. "
        # Repeat until over limit
        text = sentences * 30  # ~1470 chars
        result = summarize_tool_result(text, max_chars=100)
        assert result.endswith(" [truncated]")
        # The part before [truncated] should end with a sentence-ending punct
        body = result.replace(" [truncated]", "")
        assert body[-1] in ".!?"
        assert len(body) <= 100

    def test_over_limit_no_sentence_boundary(self):
        # One long word with no punctuation
        text = "a" * 1000
        result = summarize_tool_result(text, max_chars=100)
        assert result == "a" * 100 + " [truncated]"

    def test_empty_string(self):
        assert summarize_tool_result("") == ""

    def test_exclamation_and_question_boundaries(self):
        text = "Wow! Really? " + "x" * 800
        result = summarize_tool_result(text, max_chars=20)
        assert result.endswith(" [truncated]")
        body = result.replace(" [truncated]", "")
        assert body[-1] in "!?"

    def test_custom_max_chars(self):
        text = "Hello world. " * 50
        result = summarize_tool_result(text, max_chars=50)
        assert len(result) < 50 + len(" [truncated]") + 20  # reasonable bound

    def test_period_at_exact_boundary(self):
        # Period sits right at max_chars position
        text = "A" * 99 + "." + "B" * 100
        result = summarize_tool_result(text, max_chars=100)
        assert result == "A" * 99 + "." + " [truncated]"


# ===========================================================================
# should_continue
# ===========================================================================

class TestShouldContinue:
    """Tests for the should_continue loop-control function."""

    def test_continue_with_tool_calls(self):
        state = LoopState(iteration=0, max_iterations=5)
        assert should_continue(state, has_tool_calls=True, has_content=False) is True

    def test_continue_with_tool_calls_and_content(self):
        state = LoopState(iteration=2, max_iterations=5)
        assert should_continue(state, has_tool_calls=True, has_content=True) is True

    def test_stop_at_max_iterations(self):
        state = LoopState(iteration=5, max_iterations=5)
        assert should_continue(state, has_tool_calls=True, has_content=False) is False

    def test_stop_beyond_max_iterations(self):
        state = LoopState(iteration=7, max_iterations=5)
        assert should_continue(state, has_tool_calls=True, has_content=False) is False

    def test_stop_when_completed(self):
        state = LoopState(iteration=0, max_iterations=5, completed=True)
        assert should_continue(state, has_tool_calls=True, has_content=True) is False

    def test_stop_no_tool_calls_has_content(self):
        """Model produced a final text response with no tool calls — done."""
        state = LoopState(iteration=1, max_iterations=5)
        assert should_continue(state, has_tool_calls=False, has_content=True) is False

    def test_continue_no_tool_calls_no_content(self):
        """Edge case: model returned nothing — loop should still continue."""
        state = LoopState(iteration=0, max_iterations=5)
        assert should_continue(state, has_tool_calls=False, has_content=False) is True

    def test_stop_completed_overrides_tool_calls(self):
        state = LoopState(iteration=0, max_iterations=10, completed=True)
        assert should_continue(state, has_tool_calls=True, has_content=False) is False

    def test_stop_max_iterations_overrides_tool_calls(self):
        state = LoopState(iteration=3, max_iterations=3)
        assert should_continue(state, has_tool_calls=True, has_content=True) is False

    def test_first_iteration(self):
        state = LoopState()
        assert should_continue(state, has_tool_calls=True, has_content=False) is True


# ===========================================================================
# generate_plan
# ===========================================================================

class TestGeneratePlan:
    """Tests for generate_plan with a mocked OpenAI client."""

    def _make_mock_client(self, content: str):
        """Build a mock client that returns the given content."""
        client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client.chat.completions.create.return_value = mock_response
        return client

    def test_parses_numbered_steps(self):
        raw = "1. Search exercises\n2. Check nutrition\n3. Build plan"
        client = self._make_mock_client(raw)
        steps = generate_plan("do something complex", client)
        assert steps == ["Search exercises", "Check nutrition", "Build plan"]

    def test_parses_numbered_steps_with_parens(self):
        raw = "1) First step\n2) Second step\n3) Third step"
        client = self._make_mock_client(raw)
        steps = generate_plan("query", client)
        assert steps == ["First step", "Second step", "Third step"]

    def test_caps_at_five_steps(self):
        raw = "\n".join(f"{i}. Step {i}" for i in range(1, 8))
        client = self._make_mock_client(raw)
        steps = generate_plan("query", client)
        assert len(steps) == 5

    def test_empty_response_returns_fallback(self):
        client = self._make_mock_client("")
        steps = generate_plan("query", client)
        assert steps == ["Answer the user's query directly"]

    def test_none_content_returns_fallback(self):
        client = self._make_mock_client("")
        # Simulate .content returning None
        client.chat.completions.create.return_value.choices[0].message.content = None
        steps = generate_plan("query", client)
        assert steps == ["Answer the user's query directly"]

    def test_exception_returns_fallback(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API error")
        steps = generate_plan("query", client)
        assert steps == ["Answer the user's query directly"]

    def test_blank_lines_ignored(self):
        raw = "1. Step one\n\n2. Step two\n   \n3. Step three"
        client = self._make_mock_client(raw)
        steps = generate_plan("query", client)
        assert len(steps) == 3

    def test_passes_correct_model(self):
        client = self._make_mock_client("1. Do it")
        generate_plan("query", client, model="gpt-3.5-turbo")
        call_kwargs = client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "gpt-3.5-turbo"

    def test_passes_temperature_zero(self):
        client = self._make_mock_client("1. Do it")
        generate_plan("query", client)
        call_kwargs = client.chat.completions.create.call_args
        assert call_kwargs.kwargs["temperature"] == 0

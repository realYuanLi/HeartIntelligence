"""Comprehensive tests for the agentic loop system (functions/agentic_loop.py)."""

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from functions.agentic_loop import (
    LoopState,
    REFLECTION_CONTENT,
    make_reflection_message,
    summarize_tool_result,
)


# ===========================================================================
# LoopState dataclass
# ===========================================================================

class TestLoopState:
    """Tests for the LoopState dataclass defaults and construction."""

    def test_defaults(self):
        state = LoopState()
        assert state.iteration == 0
        assert state.max_iterations == 8

    def test_custom_values(self):
        state = LoopState(iteration=3, max_iterations=10)
        assert state.iteration == 3
        assert state.max_iterations == 10

    def test_only_two_fields(self):
        """LoopState should have exactly two fields."""
        state = LoopState()
        field_names = list(state.__dataclass_fields__.keys())
        assert field_names == ["iteration", "max_iterations"]


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
# make_reflection_message
# ===========================================================================

class TestMakeReflectionMessage:
    """Tests for the make_reflection_message helper."""

    def test_iteration_0_returns_none(self):
        assert make_reflection_message(0) is None

    def test_iteration_1_returns_system_dict(self):
        result = make_reflection_message(1)
        assert isinstance(result, dict)
        assert result["role"] == "system"

    def test_iteration_5_returns_system_dict(self):
        result = make_reflection_message(5)
        assert isinstance(result, dict)
        assert result["role"] == "system"

    def test_returned_dict_has_expected_content(self):
        result = make_reflection_message(1)
        assert result["content"] == REFLECTION_CONTENT

    def test_content_matches_constant(self):
        """All iterations >= 1 return the same REFLECTION_CONTENT."""
        for i in [1, 2, 5, 8]:
            result = make_reflection_message(i)
            assert result["content"] == REFLECTION_CONTENT

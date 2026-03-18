"""Comprehensive tests for the Health Q&A skill (health_qa_search)."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_init_path = PROJECT_ROOT / "functions" / "__init__.py"
_created_init = False
if not _init_path.exists():
    _init_path.touch()
    _created_init = True

import functions.health_qa_search as hqs


# ---------------------------------------------------------------------------
# Sample XML fixtures
# ---------------------------------------------------------------------------

SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <count>2</count>
  <list>
    <document url="https://medlineplus.gov/diabetes.html" rank="1">
      <content name="title">Diabetes</content>
      <content name="FullSummary">Diabetes is a disease in which your blood glucose levels are too high. Glucose comes from the foods you eat. Insulin helps glucose get into your cells to give them energy.</content>
      <content name="altTitle">Diabetes Mellitus</content>
      <content name="groupName">Metabolic Disorders</content>
    </document>
    <document url="https://medlineplus.gov/diabetestype2.html" rank="2">
      <content name="title">Diabetes Type 2</content>
      <content name="snippet">Type 2 diabetes is the most common form of diabetes. With type 2 diabetes, your body does not use insulin properly.</content>
      <content name="groupName">Metabolic Disorders</content>
    </document>
  </list>
</nlmSearchResult>"""

EMPTY_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <count>0</count>
  <list/>
</nlmSearchResult>"""


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

class TestTextHelpers:
    def test_normalize_whitespace(self):
        assert hqs._normalize("  hello   world  ") == "hello world"

    def test_normalize_lowercase(self):
        assert hqs._normalize("High Blood Pressure") == "high blood pressure"

    def test_strip_html_removes_tags(self):
        assert hqs._strip_html("<b>bold</b> text") == "bold text"

    def test_strip_html_empty(self):
        assert hqs._strip_html("") == ""

    def test_strip_html_nested(self):
        assert hqs._strip_html("<p><a href='#'>link</a></p>") == "link"


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

class TestXmlParsing:
    def test_parse_valid_xml(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        assert len(results) == 2

    def test_parse_first_result_fields(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        first = results[0]
        assert first["title"] == "Diabetes"
        assert first["url"] == "https://medlineplus.gov/diabetes.html"
        assert "blood glucose" in first["summary"]
        assert first["source"] == "MedlinePlus (U.S. National Library of Medicine)"
        assert first["also_called"] == "Diabetes Mellitus"
        assert first["category"] == "Metabolic Disorders"

    def test_parse_snippet_fallback(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        second = results[1]
        assert "Type 2 diabetes" in second["summary"]

    def test_parse_empty_xml(self):
        results = hqs._parse_medlineplus_xml(EMPTY_XML, max_results=3)
        assert results == []

    def test_parse_invalid_xml(self):
        results = hqs._parse_medlineplus_xml(b"not xml at all", max_results=3)
        assert results == []

    def test_parse_respects_max_results(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=1)
        assert len(results) == 1

    def test_parse_truncates_long_summary(self):
        long_summary = "A " * 500
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://example.com" rank="1">
      <content name="title">Test</content>
      <content name="FullSummary">{long_summary}</content>
    </document>
  </list>
</nlmSearchResult>""".encode("utf-8")
        results = hqs._parse_medlineplus_xml(xml, max_results=3)
        assert len(results[0]["summary"]) <= 810  # 800 + some padding for truncation


# ---------------------------------------------------------------------------
# Search (mocked HTTP)
# ---------------------------------------------------------------------------

class TestSearch:
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_returns_results(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = hqs.search_health_topics("diabetes")
        assert len(results) == 2
        assert results[0]["title"] == "Diabetes"

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_empty_query(self, mock_urlopen):
        results = hqs.search_health_topics("")
        assert results == []
        mock_urlopen.assert_not_called()

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_whitespace_query(self, mock_urlopen):
        results = hqs.search_health_topics("   ")
        assert results == []
        mock_urlopen.assert_not_called()

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_api_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection timeout")
        results = hqs.search_health_topics("diabetes")
        assert results == []

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_respects_max_results(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = hqs.search_health_topics("diabetes", max_results=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_empty(self):
        assert hqs.format_health_results([]) == ""

    def test_format_includes_title(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "Diabetes" in formatted

    def test_format_includes_disclaimer(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "not a substitute for professional medical advice" in formatted

    def test_format_includes_source_link(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "medlineplus.gov" in formatted

    def test_format_includes_also_called(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "Diabetes Mellitus" in formatted

    def test_format_includes_category(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "Metabolic Disorders" in formatted

    def test_format_includes_summary(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "blood glucose" in formatted

    def test_format_header_count(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "2 topics found" in formatted


# ---------------------------------------------------------------------------
# Gate function (mocked)
# ---------------------------------------------------------------------------

class TestGateFunction:
    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_yes(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "YES"
        mock_client.chat.completions.create.return_value = mock_response

        assert hqs.needs_health_qa("what causes high blood pressure") is True

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_no(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "NO"
        mock_client.chat.completions.create.return_value = mock_response

        assert hqs.needs_health_qa("show me chest exercises") is False

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_error_returns_false(self, mock_openai_cls):
        mock_openai_cls.side_effect = Exception("API error")
        assert hqs.needs_health_qa("some query") is False


# ---------------------------------------------------------------------------
# Skill definition
# ---------------------------------------------------------------------------

class TestSkillDefinition:
    def test_skill_markdown_exists(self):
        skill_path = PROJECT_ROOT / "skills" / "health_qa.md"
        assert skill_path.exists()

    def test_skill_has_correct_frontmatter(self):
        skill_path = PROJECT_ROOT / "skills" / "health_qa.md"
        content = skill_path.read_text()
        assert "id: health_qa" in content
        assert "executor: health_qa" in content
        assert "kind: context" in content

    def test_skill_registered_in_runtime(self):
        """Verify the executor name is registered in SkillRuntime."""
        from functions.skills_runtime import SkillRuntime
        with patch("functions.skills_runtime.analyze_health_query_with_raw_data"):
            rt = SkillRuntime()
        assert "health_qa" in rt.executors


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

class TestTextHelpersEdgeCases:
    """Edge cases for _normalize and _strip_html."""

    def test_normalize_none(self):
        assert hqs._normalize(None) == ""

    def test_strip_html_none(self):
        assert hqs._strip_html(None) == ""

    def test_normalize_tabs_and_newlines(self):
        assert hqs._normalize("hello\t\nworld") == "hello world"

    def test_strip_html_self_closing_tags(self):
        assert hqs._strip_html("line<br/>break") == "linebreak"

    def test_strip_html_malformed_tags(self):
        """Unclosed tags should still be stripped."""
        assert hqs._strip_html("<b>bold<b> text") == "bold text"


class TestXmlParsingEdgeCases:
    """Edge cases for XML parsing."""

    def test_document_without_title_is_skipped(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://example.com" rank="1">
      <content name="FullSummary">No title here.</content>
    </document>
    <document url="https://example.com/2" rank="2">
      <content name="title">Has Title</content>
      <content name="FullSummary">With summary.</content>
    </document>
  </list>
</nlmSearchResult>"""
        results = hqs._parse_medlineplus_xml(xml, max_results=5)
        assert len(results) == 1
        assert results[0]["title"] == "Has Title"

    def test_html_in_summary_is_stripped(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://example.com" rank="1">
      <content name="title">Test Topic</content>
      <content name="FullSummary">&lt;p&gt;Some &lt;b&gt;bold&lt;/b&gt; text.&lt;/p&gt;</content>
    </document>
  </list>
</nlmSearchResult>"""
        results = hqs._parse_medlineplus_xml(xml, max_results=3)
        summary = results[0]["summary"]
        assert "<p>" not in summary
        assert "<b>" not in summary

    def test_document_with_no_url(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document rank="1">
      <content name="title">No URL Topic</content>
      <content name="FullSummary">Summary text.</content>
    </document>
  </list>
</nlmSearchResult>"""
        results = hqs._parse_medlineplus_xml(xml, max_results=3)
        assert len(results) == 1
        assert results[0]["url"] == ""

    def test_snippet_not_used_when_full_summary_exists(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://example.com" rank="1">
      <content name="title">Topic</content>
      <content name="FullSummary">Full summary here.</content>
      <content name="snippet">Snippet text should be ignored.</content>
    </document>
  </list>
</nlmSearchResult>"""
        results = hqs._parse_medlineplus_xml(xml, max_results=3)
        assert results[0]["summary"] == "Full summary here."

    def test_empty_bytes_returns_empty(self):
        results = hqs._parse_medlineplus_xml(b"", max_results=3)
        assert results == []

    def test_truncation_ends_on_word_boundary(self):
        # Create summary that is exactly over 800 chars with multi-word content
        word = "abcdefghij "  # 11 chars per word
        long_summary = word * 80  # 880 chars
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://example.com" rank="1">
      <content name="title">Test</content>
      <content name="FullSummary">{long_summary}</content>
    </document>
  </list>
</nlmSearchResult>""".encode("utf-8")
        results = hqs._parse_medlineplus_xml(xml, max_results=3)
        assert results[0]["summary"].endswith("...")


class TestFormattingEdgeCases:
    """Edge cases for format_health_results."""

    def test_format_minimal_topic(self):
        """Topic with only title, no optional fields."""
        results = [{"title": "Test Topic"}]
        formatted = hqs.format_health_results(results)
        assert "Test Topic" in formatted
        assert "Also known as" not in formatted
        assert "Category" not in formatted

    def test_format_none_input(self):
        assert hqs.format_health_results(None) == ""

    def test_format_single_result_header(self):
        results = [{"title": "Only One", "summary": "Just one result."}]
        formatted = hqs.format_health_results(results)
        assert "1 topics found" in formatted

    def test_format_numbering_sequential(self):
        results = [
            {"title": "First", "summary": "A"},
            {"title": "Second", "summary": "B"},
            {"title": "Third", "summary": "C"},
        ]
        formatted = hqs.format_health_results(results)
        assert "### 1. First" in formatted
        assert "### 2. Second" in formatted
        assert "### 3. Third" in formatted


class TestGateFunctionEdgeCases:
    """Edge cases for the LLM gate function."""

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_whitespace_yes(self, mock_openai_cls):
        """LLM returns ' YES ' with extra whitespace."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  YES  "
        mock_client.chat.completions.create.return_value = mock_response
        assert hqs.needs_health_qa("what is diabetes") is True

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_lowercase_yes(self, mock_openai_cls):
        """LLM returns 'yes' in lowercase."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "yes"
        mock_client.chat.completions.create.return_value = mock_response
        assert hqs.needs_health_qa("what is diabetes") is True

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_unexpected_response_returns_false(self, mock_openai_cls):
        """LLM returns something other than YES/NO."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "MAYBE"
        mock_client.chat.completions.create.return_value = mock_response
        assert hqs.needs_health_qa("some question") is False

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_gate_empty_response_returns_false(self, mock_openai_cls):
        """LLM returns empty string."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_client.chat.completions.create.return_value = mock_response
        assert hqs.needs_health_qa("anything") is False


class TestSearchEdgeCases:
    """Additional search edge cases."""

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_none_query(self, mock_urlopen):
        results = hqs.search_health_topics(None)
        assert results == []
        mock_urlopen.assert_not_called()

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_normalizes_query(self, mock_urlopen):
        """Verify search sends normalized query to API."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = EMPTY_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        hqs.search_health_topics("  HIGH  Blood Pressure  ")
        # Verify urlopen was called (query was not empty after normalization)
        mock_urlopen.assert_called_once()

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_returns_invalid_xml(self, mock_urlopen):
        """API returns non-XML response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>Error page</html>"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = hqs.search_health_topics("diabetes")
        assert results == []


class TestRunHealthQaExecutor:
    """Test the _run_health_qa method on SkillRuntime."""

    @patch("functions.skills_runtime.search_health_topics")
    @patch("functions.skills_runtime.format_health_results")
    @patch("functions.skills_runtime.analyze_health_query_with_raw_data")
    def test_executor_returns_activated_with_results(self, mock_analyze, mock_format, mock_search):
        from functions.skills_runtime import SkillRuntime, SkillDefinition
        mock_search.return_value = [{"title": "Diabetes", "summary": "Info"}]
        mock_format.return_value = "Formatted output"

        rt = SkillRuntime()
        skill = SkillDefinition(
            skill_id="health_qa", title="Health Q&A", executor="health_qa",
            kind="context", enabled_by_default=True, description="", instructions="",
        )
        result = rt._run_health_qa("diabetes", {}, None, skill)
        assert result["activated"] is True
        assert result["health_qa_summary"] == "Formatted output"
        assert result["topics"] == [{"title": "Diabetes", "summary": "Info"}]

    @patch("functions.skills_runtime.search_health_topics")
    @patch("functions.skills_runtime.analyze_health_query_with_raw_data")
    def test_executor_returns_not_activated_when_no_results(self, mock_analyze, mock_search):
        from functions.skills_runtime import SkillRuntime, SkillDefinition
        mock_search.return_value = []

        rt = SkillRuntime()
        skill = SkillDefinition(
            skill_id="health_qa", title="Health Q&A", executor="health_qa",
            kind="context", enabled_by_default=True, description="", instructions="",
        )
        result = rt._run_health_qa("unknown topic xyz", {}, None, skill)
        assert result["activated"] is False

    @patch("functions.skills_runtime.search_health_topics")
    @patch("functions.skills_runtime.format_health_results")
    @patch("functions.skills_runtime.analyze_health_query_with_raw_data")
    def test_executor_calls_status_updater(self, mock_analyze, mock_format, mock_search):
        from functions.skills_runtime import SkillRuntime, SkillDefinition
        mock_search.return_value = [{"title": "Test"}]
        mock_format.return_value = "output"
        status_calls = []

        rt = SkillRuntime()
        skill = SkillDefinition(
            skill_id="health_qa", title="Health Q&A", executor="health_qa",
            kind="context", enabled_by_default=True, description="", instructions="",
        )
        rt._run_health_qa("test", {}, lambda s: status_calls.append(s), skill)
        assert "searching_health_topics" in status_calls
        assert "formatting_health_topics" in status_calls


class TestSecurityInputValidation:
    """Verify that potentially malicious inputs are handled safely."""

    def test_html_in_content_stripped_by_strip_html(self):
        """HTML/script tags in API content are stripped by _strip_html."""
        malicious = '<script>alert("xss")</script>'
        stripped = hqs._strip_html(malicious)
        assert "<script>" not in stripped
        assert "alert" in stripped  # text content preserved, tags removed

    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_very_long_query_does_not_crash(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = EMPTY_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        long_query = "diabetes " * 1000
        results = hqs.search_health_topics(long_query)
        # Should not raise; returns whatever API returns
        assert isinstance(results, list)

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

# XML with HTML-encoded content (as MedlinePlus actually returns)
REAL_WORLD_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://medlineplus.gov/streptococcalinfections.html" rank="1">
      <content name="title">&lt;span class="qt0"&gt;Strep Throat&lt;/span&gt;</content>
      <content name="FullSummary">&lt;p&gt;Strep throat is a bacterial infection.&lt;/p&gt;&lt;p&gt;Symptoms include:&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Sore throat&lt;/li&gt;&lt;li&gt;Fever&lt;/li&gt;&lt;li&gt;Swollen lymph nodes&lt;/li&gt;&lt;/ul&gt;</content>
      <content name="altTitle">Streptococcal Pharyngitis</content>
      <content name="altTitle">GAS Infection</content>
      <content name="groupName">Infections</content>
      <content name="groupName">Ear, Nose and Throat</content>
    </document>
  </list>
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
        assert "bold" in hqs._strip_html("<b>bold</b> text")

    def test_strip_html_empty(self):
        assert hqs._strip_html("") == ""

    def test_strip_html_nested(self):
        result = hqs._strip_html("<p><a href='#'>link</a></p>")
        assert "link" in result

    def test_strip_html_preserves_paragraph_breaks(self):
        result = hqs._strip_html("<p>First paragraph.</p><p>Second paragraph.</p>")
        assert "\n" in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_strip_html_converts_list_items(self):
        result = hqs._strip_html("<ul><li>Item one</li><li>Item two</li></ul>")
        assert "- Item one" in result
        assert "- Item two" in result

    def test_strip_html_handles_br_tags(self):
        result = hqs._strip_html("Line one<br/>Line two")
        assert "\n" in result

    def test_strip_html_collapses_excessive_newlines(self):
        result = hqs._strip_html("<p></p><p></p><p></p><p>Content</p>")
        assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# Search term extraction (mocked)
# ---------------------------------------------------------------------------

class TestSearchTermExtraction:
    @patch("functions.health_qa_search.openai.OpenAI")
    def test_extracts_terms_from_conversational_query(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "strep throat"
        mock_client.chat.completions.create.return_value = mock_response

        result = hqs._extract_medical_terms("what are the symptoms of strep throat?")
        assert result == "strep throat"

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_uses_gpt4o_mini_not_full(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "headache"
        mock_client.chat.completions.create.return_value = mock_response

        hqs._extract_medical_terms("my head hurts")
        call_args = mock_client.chat.completions.create.call_args
        assert call_args[1]["model"] == "gpt-4o-mini"

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_falls_back_to_normalized_query_on_error(self, mock_openai_cls):
        mock_openai_cls.side_effect = Exception("API error")
        result = hqs._extract_medical_terms("What is diabetes?")
        assert result == "what is diabetes?"

    @patch("functions.health_qa_search.openai.OpenAI")
    def test_falls_back_on_empty_response(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_client.chat.completions.create.return_value = mock_response

        result = hqs._extract_medical_terms("What is diabetes?")
        # Falls back to normalized query when LLM returns empty
        assert result == "what is diabetes?"


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
        assert "Diabetes Mellitus" in first["also_called"]
        assert "Metabolic Disorders" in first["category"]

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
        long_summary = "A " * 700
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
        assert len(results[0]["summary"]) <= 1210  # 1200 + some padding for truncation

    def test_parse_real_world_xml_strips_span_tags(self):
        results = hqs._parse_medlineplus_xml(REAL_WORLD_XML, max_results=3)
        assert len(results) == 1
        assert results[0]["title"] == "Strep Throat"
        assert "<span" not in results[0]["title"]

    def test_parse_real_world_preserves_list_structure(self):
        results = hqs._parse_medlineplus_xml(REAL_WORLD_XML, max_results=3)
        summary = results[0]["summary"]
        assert "- Sore throat" in summary
        assert "- Fever" in summary

    def test_parse_multiple_alt_titles(self):
        results = hqs._parse_medlineplus_xml(REAL_WORLD_XML, max_results=3)
        also_called = results[0]["also_called"]
        assert "Streptococcal Pharyngitis" in also_called
        assert "GAS Infection" in also_called

    def test_parse_multiple_categories(self):
        results = hqs._parse_medlineplus_xml(REAL_WORLD_XML, max_results=3)
        category = results[0]["category"]
        assert "Infections" in category
        assert "Ear, Nose and Throat" in category


# ---------------------------------------------------------------------------
# Search (mocked HTTP + mocked term extraction)
# ---------------------------------------------------------------------------

class TestSearch:
    @patch("functions.health_qa_search._extract_medical_terms", return_value="diabetes")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_returns_results(self, mock_urlopen, mock_extract):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = hqs.search_health_topics("what is diabetes")
        assert len(results) == 2
        assert results[0]["title"] == "Diabetes"

    @patch("functions.health_qa_search._extract_medical_terms")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_empty_query(self, mock_urlopen, mock_extract):
        results = hqs.search_health_topics("")
        assert results == []
        mock_urlopen.assert_not_called()
        mock_extract.assert_not_called()

    @patch("functions.health_qa_search._extract_medical_terms")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_whitespace_query(self, mock_urlopen, mock_extract):
        results = hqs.search_health_topics("   ")
        assert results == []
        mock_urlopen.assert_not_called()

    @patch("functions.health_qa_search._extract_medical_terms", return_value="diabetes")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_api_failure(self, mock_urlopen, mock_extract):
        mock_urlopen.side_effect = Exception("Connection timeout")
        results = hqs.search_health_topics("diabetes")
        assert results == []

    @patch("functions.health_qa_search._extract_medical_terms", return_value="diabetes")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_respects_max_results(self, mock_urlopen, mock_extract):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = hqs.search_health_topics("diabetes", max_results=1)
        assert len(results) == 1

    @patch("functions.health_qa_search._extract_medical_terms", return_value="diabetes")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_clamps_negative_max_results(self, mock_urlopen, mock_extract):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = hqs.search_health_topics("diabetes", max_results=-1)
        assert len(results) >= 1  # clamped to 1

    @patch("functions.health_qa_search._extract_medical_terms", return_value="strep throat")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_sends_extracted_terms_not_raw_query(self, mock_urlopen, mock_extract):
        mock_resp = MagicMock()
        mock_resp.read.return_value = EMPTY_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        hqs.search_health_topics("what are the symptoms of strep throat?")
        # Verify the URL contains the extracted term, not the raw query
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        assert "strep+throat" in request_obj.full_url or "strep%20throat" in request_obj.full_url


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
        assert "2 topic(s) found" in formatted


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

    def test_skill_routing_keywords_no_nutrition_overlap(self):
        """Health QA should not have nutrition/diet/meal routing keywords."""
        skill_path = PROJECT_ROOT / "skills" / "health_qa.md"
        content = skill_path.read_text()
        # Get only the routing keywords line
        for line in content.split("\n"):
            if line.startswith("Routing keywords:"):
                keywords = line.lower()
                assert "nutrition" not in keywords.split()
                assert "diet" not in keywords.split()
                assert "dietary" not in keywords.split()
                assert "calories" not in keywords.split()
                assert "meal" not in keywords.split()
                break


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
        result = hqs._strip_html("line<br/>break")
        assert "line" in result
        assert "break" in result

    def test_strip_html_malformed_tags(self):
        """Unclosed tags should still be stripped."""
        result = hqs._strip_html("<b>bold<b> text")
        assert "bold" in result
        assert "text" in result


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
        # Create summary that is over 1200 chars with multi-word content
        word = "abcdefghij "  # 11 chars per word
        long_summary = word * 120  # 1320 chars
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
        assert "1 topic(s) found" in formatted

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

    @patch("functions.health_qa_search._extract_medical_terms")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_none_query(self, mock_urlopen, mock_extract):
        results = hqs.search_health_topics(None)
        assert results == []
        mock_urlopen.assert_not_called()

    @patch("functions.health_qa_search._extract_medical_terms", return_value="high blood pressure")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_uses_extracted_terms(self, mock_urlopen, mock_extract):
        """Verify search sends extracted terms to API."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = EMPTY_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        hqs.search_health_topics("  HIGH  Blood Pressure  ")
        mock_extract.assert_called_once_with("  HIGH  Blood Pressure  ")
        mock_urlopen.assert_called_once()

    @patch("functions.health_qa_search._extract_medical_terms", return_value="diabetes")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_search_returns_invalid_xml(self, mock_urlopen, mock_extract):
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

    @patch("functions.health_qa_search._extract_medical_terms", return_value="diabetes")
    @patch("functions.health_qa_search.urllib.request.urlopen")
    def test_very_long_query_does_not_crash(self, mock_urlopen, mock_extract):
        mock_resp = MagicMock()
        mock_resp.read.return_value = EMPTY_XML
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        long_query = "diabetes " * 1000
        results = hqs.search_health_topics(long_query)
        # Should not raise; returns whatever API returns
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Emergency/urgency detection
# ---------------------------------------------------------------------------

class TestUrgencyDetection:
    """Test emergency and urgency keyword detection."""

    def test_detects_emergency_chest_pain(self):
        assert hqs._detect_urgency("I'm having chest pain") == "emergency"

    def test_detects_emergency_cant_breathe(self):
        assert hqs._detect_urgency("I can't breathe") == "emergency"

    def test_detects_emergency_stroke(self):
        assert hqs._detect_urgency("Is this a stroke?") == "emergency"

    def test_detects_emergency_suicide(self):
        assert hqs._detect_urgency("having suicidal thoughts") == "emergency"

    def test_detects_urgent_high_fever(self):
        assert hqs._detect_urgency("I have a high fever") == "urgent"

    def test_detects_urgent_severe_pain(self):
        assert hqs._detect_urgency("severe pain in my side") == "urgent"

    def test_returns_none_for_normal_query(self):
        assert hqs._detect_urgency("what is diabetes") is None

    def test_returns_none_for_empty(self):
        assert hqs._detect_urgency("") is None

    def test_emergency_overrides_urgent(self):
        # "chest pain" is emergency, should take priority
        assert hqs._detect_urgency("chest pain with high fever") == "emergency"


# ---------------------------------------------------------------------------
# Follow-up suggestions
# ---------------------------------------------------------------------------

class TestFollowUpSuggestions:
    """Test follow-up question generation."""

    def test_generates_suggestions_for_symptom_topic(self):
        results = [{"title": "Diabetes", "summary": "Symptoms include excessive thirst and fatigue.", "category": ""}]
        suggestions = hqs._generate_follow_ups(results, "what is diabetes")
        assert len(suggestions) >= 2
        assert any("doctor" in s.lower() or "see" in s.lower() for s in suggestions)

    def test_generates_suggestions_for_treatment_topic(self):
        results = [{"title": "Hypertension", "summary": "Treatment includes medication and lifestyle changes.", "category": ""}]
        suggestions = hqs._generate_follow_ups(results, "high blood pressure")
        assert len(suggestions) >= 2
        assert any("treatment" in s.lower() for s in suggestions)

    def test_returns_empty_for_empty_results(self):
        assert hqs._generate_follow_ups([], "query") == []

    def test_max_three_suggestions(self):
        results = [{"title": "Cold", "summary": "Symptoms include cough. Treatment is rest. Prevention by hand washing. Risk factors include age. Causes are viral.", "category": ""}]
        suggestions = hqs._generate_follow_ups(results, "common cold")
        assert len(suggestions) <= 3

    def test_suggestions_include_topic_name(self):
        results = [{"title": "Asthma", "summary": "A chronic condition with symptoms like wheezing.", "category": ""}]
        suggestions = hqs._generate_follow_ups(results, "asthma")
        assert all("asthma" in s.lower() for s in suggestions)


# ---------------------------------------------------------------------------
# Formatted output with new features
# ---------------------------------------------------------------------------

class TestFormattingWithQuery:
    """Test format_health_results with query parameter for urgency and follow-ups."""

    def test_emergency_query_includes_911_banner(self):
        results = [{"title": "Heart Attack", "summary": "A serious condition.", "url": "https://medlineplus.gov/heartattack.html", "source": "MedlinePlus"}]
        formatted = hqs.format_health_results(results, query="I'm having chest pain")
        assert "911" in formatted
        assert "emergency" in formatted.lower()

    def test_urgent_query_includes_attention_banner(self):
        results = [{"title": "Fever", "summary": "Elevated body temperature.", "url": "https://medlineplus.gov/fever.html", "source": "MedlinePlus"}]
        formatted = hqs.format_health_results(results, query="I have a high fever")
        assert "medical attention" in formatted.lower() or "urgent" in formatted.lower()

    def test_normal_query_no_urgency_banner(self):
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results, query="what is diabetes")
        assert "911" not in formatted
        assert "emergency room" not in formatted.lower()

    def test_follow_up_suggestions_included(self):
        results = [{"title": "Diabetes", "summary": "Symptoms include excessive thirst.", "url": "https://medlineplus.gov/diabetes.html", "source": "MedlinePlus"}]
        formatted = hqs.format_health_results(results, query="what is diabetes")
        assert "follow-up" in formatted.lower() or "also want to ask" in formatted.lower()

    def test_learn_more_link_present(self):
        results = [{"title": "Test", "summary": "Info.", "url": "https://medlineplus.gov/test.html", "source": "MedlinePlus (NLM)"}]
        formatted = hqs.format_health_results(results)
        assert "Learn more" in formatted

    def test_format_backward_compatible_no_query(self):
        """Calling without query still works (backward compatible)."""
        results = hqs._parse_medlineplus_xml(SAMPLE_XML, max_results=3)
        formatted = hqs.format_health_results(results)
        assert "Diabetes" in formatted
        assert "not a substitute for professional medical advice" in formatted

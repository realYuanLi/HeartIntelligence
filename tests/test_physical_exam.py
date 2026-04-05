"""Comprehensive tests for the Physical Exam Interpreter skill (physical_exam_search)."""

import json
import sys
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

import functions.physical_exam_search as pes

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_findings_cache():
    """Reset the module-level lazy cache between tests."""
    pes._FINDINGS = None
    yield
    pes._FINDINGS = None


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

class TestDatabaseLoading:
    def test_load_findings_returns_list(self):
        findings = pes._load_findings()
        assert isinstance(findings, list)
        assert len(findings) > 0

    def test_all_findings_have_required_fields(self):
        findings = pes._load_findings()
        required = {"system", "finding", "aliases", "description", "clinical_significance",
                     "severity_indicator", "follow_up_assessments"}
        for f in findings:
            missing = required - set(f.keys())
            assert not missing, f"Finding '{f.get('finding', '?')}' missing fields: {missing}"

    def test_severity_values_are_valid(self):
        valid = {"critical", "high", "moderate", "low"}
        for f in pes._load_findings():
            assert f["severity_indicator"] in valid, f"Invalid severity in '{f['finding']}'"

    def test_all_systems_represented(self):
        systems = {f["system"] for f in pes._load_findings()}
        expected = {"cardiovascular", "respiratory", "neurological", "musculoskeletal",
                    "abdomen", "dermatological", "HEENT", "vascular", "endocrine"}
        assert expected.issubset(systems)

    def test_clinical_significance_is_nonempty(self):
        for f in pes._load_findings():
            assert len(f["clinical_significance"]) > 0, f"Empty significance in '{f['finding']}'"


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

class TestTextHelpers:
    def test_normalize_whitespace(self):
        assert pes._normalize("  hello   world  ") == "hello world"

    def test_normalize_lowercase(self):
        assert pes._normalize("Heart MURMUR") == "heart murmur"

    def test_stem_plural(self):
        assert pes._stem("crackles") == "crackle"
        assert pes._stem("murmurs") == "murmur"

    def test_stem_no_change(self):
        assert pes._stem("mass") == "mass"
        assert pes._stem("s3") == "s3"

    def test_tokenize(self):
        tokens = pes._tokenize("S3 Gallop in early diastole")
        assert "s3" in tokens
        assert "gallop" in tokens
        assert "diastole" in tokens


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_by_finding_name(self):
        results = pes.search_findings("S3 gallop")
        assert len(results) > 0
        assert results[0]["finding"] == "S3 gallop"

    def test_search_by_alias(self):
        results = pes.search_findings("third heart sound")
        assert any(r["finding"] == "S3 gallop" for r in results)

    def test_search_babinski(self):
        results = pes.search_findings("Babinski sign positive upgoing toes")
        assert results[0]["finding"] == "Babinski sign positive"

    def test_search_by_system_keyword(self):
        results = pes.search_findings("lung findings")
        systems = {r["system"] for r in results}
        assert "respiratory" in systems

    def test_search_cardiac_keyword(self):
        results = pes.search_findings("heart exam findings")
        systems = {r["system"] for r in results}
        assert "cardiovascular" in systems

    def test_search_multi_system(self):
        results = pes.search_findings("JVD crackles edema")
        finding_names = {r["finding"] for r in results}
        # Should find at least JVD and crackles
        assert "Jugular venous distension" in finding_names or "Crackles (rales)" in finding_names

    def test_search_empty_query(self):
        results = pes.search_findings("")
        assert results == []

    def test_search_stop_words_only(self):
        results = pes.search_findings("what does the patient finding mean")
        assert results == []

    def test_search_max_results(self):
        results = pes.search_findings("heart murmur sound", max_results=3)
        assert len(results) <= 3

    def test_search_by_condition(self):
        results = pes.search_findings("meningitis signs")
        finding_names = {r["finding"] for r in results}
        assert "Nuchal rigidity" in finding_names

    def test_search_emergency_findings(self):
        results = pes.search_findings("stridor upper airway")
        assert results[0]["finding"] == "Stridor"
        assert results[0]["severity_indicator"] == "critical"

    def test_search_abdominal_findings(self):
        results = pes.search_findings("rebound tenderness abdomen")
        assert any(r["finding"] == "Rebound tenderness" for r in results)

    def test_search_musculoskeletal(self):
        results = pes.search_findings("anterior drawer knee ACL")
        assert any("drawer" in r["finding"].lower() for r in results)

    def test_search_dermatological(self):
        results = pes.search_findings("purpura petechiae non-blanching rash")
        assert any(r["finding"] == "Purpura" for r in results)

    def test_search_papilledema(self):
        results = pes.search_findings("papilledema optic disc swelling")
        assert results[0]["finding"] == "Papilledema"
        assert results[0]["severity_indicator"] == "critical"

    def test_search_returns_follow_up(self):
        results = pes.search_findings("S3 gallop")
        assert len(results[0]["follow_up_assessments"]) > 0


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_empty(self):
        assert pes.format_finding_results([]) == ""

    def test_format_includes_disclaimer(self):
        results = pes.search_findings("S3 gallop")
        formatted = pes.format_finding_results(results[:1])
        assert "not a diagnostic tool" in formatted.lower()

    def test_format_includes_finding_name(self):
        results = pes.search_findings("S3 gallop")
        formatted = pes.format_finding_results(results[:1])
        assert "S3 gallop" in formatted

    def test_format_includes_severity(self):
        results = pes.search_findings("S3 gallop")
        formatted = pes.format_finding_results(results[:1])
        assert "HIGH" in formatted

    def test_format_includes_follow_up(self):
        results = pes.search_findings("S3 gallop")
        formatted = pes.format_finding_results(results[:1])
        assert "Echocardiogram" in formatted

    def test_format_includes_clinical_significance(self):
        results = pes.search_findings("Babinski")
        formatted = pes.format_finding_results(results[:1])
        assert "upper motor neuron" in formatted.lower() or "UMN" in formatted or "corticospinal" in formatted.lower()

    def test_format_includes_documentation_note(self):
        results = pes.search_findings("papilledema")
        formatted = pes.format_finding_results(results[:1])
        assert "Documentation Guidance" in formatted

    def test_format_includes_references(self):
        results = pes.search_findings("S3 gallop")
        formatted = pes.format_finding_results(results[:1])
        assert "Bates" in formatted


class TestStructuredExamNote:
    def test_structured_note_empty(self):
        assert pes.format_structured_exam_note([]) == ""

    def test_structured_note_groups_by_system(self):
        results = pes.search_findings("JVD crackles edema")
        note = pes.format_structured_exam_note(results[:5])
        # Should have system headers
        assert "Cardiovascular" in note or "Respiratory" in note

    def test_structured_note_includes_query(self):
        results = pes.search_findings("S3 gallop")
        note = pes.format_structured_exam_note(results[:1], "patient has S3 gallop")
        assert "patient has S3 gallop" in note

    def test_structured_note_includes_priority_key(self):
        results = pes.search_findings("S3 gallop")
        note = pes.format_structured_exam_note(results[:1])
        assert "Priority key" in note

    def test_structured_note_severity_icons(self):
        results = pes.search_findings("papilledema")
        note = pes.format_structured_exam_note(results[:1])
        assert "[!]" in note  # critical severity


# ---------------------------------------------------------------------------
# Gate function (mocked)
# ---------------------------------------------------------------------------

class TestGateFunction:
    @patch("functions.physical_exam_search.openai.OpenAI")
    def test_gate_yes(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "YES"
        mock_client.chat.completions.create.return_value = mock_response

        assert pes.needs_physical_exam_data("what does an S3 gallop mean") is True

    @patch("functions.physical_exam_search.openai.OpenAI")
    def test_gate_no(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "NO"
        mock_client.chat.completions.create.return_value = mock_response

        assert pes.needs_physical_exam_data("recommend a workout plan") is False

    @patch("functions.physical_exam_search.openai.OpenAI")
    def test_gate_error_returns_false(self, mock_openai_cls):
        mock_openai_cls.side_effect = Exception("API error")
        assert pes.needs_physical_exam_data("some query") is False


# ---------------------------------------------------------------------------
# Skill definition
# ---------------------------------------------------------------------------

class TestSkillDefinition:
    def test_skill_markdown_exists(self):
        skill_path = PROJECT_ROOT / "skills" / "physical_exam_interpreter.md"
        assert skill_path.exists()

    def test_skill_has_correct_frontmatter(self):
        skill_path = PROJECT_ROOT / "skills" / "physical_exam_interpreter.md"
        content = skill_path.read_text()
        assert "id: physical_exam_interpreter" in content
        assert "executor: physical_exam_interpreter" in content
        assert "kind: context" in content

    def test_skill_registered_in_runtime(self):
        """Verify the executor name is registered in SkillRuntime."""
        # Import to check executor registry
        from functions.skills_runtime import SkillRuntime
        with patch("functions.skills_runtime.analyze_health_query_with_raw_data"):
            rt = SkillRuntime()
        assert "physical_exam_interpreter" in rt.executors

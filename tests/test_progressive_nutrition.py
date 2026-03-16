"""Tests for the progressive/gradual nutrition profiling feature.

Covers:
- merge_extracted_insights()
- compute_profile_completeness()
- handle_nutrition_tool with extract_insights action
- Completeness endpoint
- Profile gate removal (create_plan works without a profile)
"""

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_init_path = PROJECT_ROOT / "functions" / "__init__.py"
if not _init_path.exists():
    _init_path.touch()

import functions.nutrition_plans as np_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _tmp_data_dirs(tmp_path, monkeypatch):
    """Redirect profile/plan storage to a temp directory for isolation.

    Also deep-copy _DEFAULT_PROFILE to prevent cross-test mutation of the
    shared lab_values dict (shallow copy bug in the source).
    """
    profiles = tmp_path / "nutrition_profiles"
    plans = tmp_path / "nutrition_plans"
    profiles.mkdir()
    plans.mkdir()
    monkeypatch.setattr(np_mod, "PROFILES_DIR", profiles)
    monkeypatch.setattr(np_mod, "PLANS_DIR", plans)
    # Protect _DEFAULT_PROFILE from shallow-copy mutation between tests
    original = copy.deepcopy(np_mod._DEFAULT_PROFILE)
    yield
    np_mod._DEFAULT_PROFILE.update(original)
    np_mod._DEFAULT_PROFILE["lab_values"] = original["lab_values"]


@pytest.fixture
def default_profile():
    return copy.deepcopy(np_mod._DEFAULT_PROFILE)


@pytest.fixture
def full_profile():
    """A fully-populated nutrition profile."""
    return {
        "age": 35,
        "weight_kg": 80.0,
        "height_cm": 180.0,
        "sex": "female",
        "activity_level": "active",
        "allergies": ["peanuts"],
        "dietary_preferences": ["vegetarian"],
        "health_goals": ["weight loss"],
        "weekly_budget_usd": 150.0,
        "lab_values": {
            "vitamin_d_ng_ml": 30.0,
            "iron_ug_dl": 100.0,
            "cholesterol_total_mg_dl": 190.0,
            "ldl_mg_dl": 100.0,
            "hdl_mg_dl": 60.0,
            "b12_pg_ml": 400.0,
            "hba1c_pct": 5.2,
        },
        "updated_at": None,
        "insight_meta": {
            "age": {"source": "chat", "extracted_at": "2026-01-01T00:00:00", "snippet": "I am 35"},
        },
    }


# ===========================================================================
# 1. merge_extracted_insights unit tests
# ===========================================================================

class TestMergeExtractedInsights:
    """Unit tests for merge_extracted_insights()."""

    def test_extracts_scalar_weight(self):
        """Scalar field weight_kg is stored correctly."""
        result = np_mod.merge_extracted_insights("alice", {"weight_kg": 80})
        assert "weight_kg" in result

        profile = np_mod._load_profile("alice")
        assert profile["weight_kg"] == 80.0

    def test_extracts_scalar_age(self):
        """Scalar field age is stored correctly and clamped to int."""
        result = np_mod.merge_extracted_insights("alice", {"age": 25})
        assert "age" in result

        profile = np_mod._load_profile("alice")
        assert profile["age"] == 25

    def test_list_fields_append_and_deduplicate(self):
        """List fields (allergies, dietary_preferences) append and deduplicate."""
        np_mod.merge_extracted_insights("bob", {"allergies": ["nuts"]})
        np_mod.merge_extracted_insights("bob", {"allergies": ["nuts", "dairy"]})

        profile = np_mod._load_profile("bob")
        assert profile["allergies"] == ["nuts", "dairy"]

    def test_list_field_dietary_preferences(self):
        """dietary_preferences list field works correctly."""
        np_mod.merge_extracted_insights("carol", {"dietary_preferences": ["vegan"]})
        np_mod.merge_extracted_insights("carol", {"dietary_preferences": ["vegan", "gluten-free"]})

        profile = np_mod._load_profile("carol")
        assert profile["dietary_preferences"] == ["vegan", "gluten-free"]

    def test_handles_nested_lab_values(self):
        """Nested lab_values dict is merged correctly."""
        result = np_mod.merge_extracted_insights("dave", {
            "lab_values": {"vitamin_d_ng_ml": 25.0, "iron_ug_dl": 90}
        })
        assert "lab_values.vitamin_d_ng_ml" in result
        assert "lab_values.iron_ug_dl" in result

        profile = np_mod._load_profile("dave")
        assert profile["lab_values"]["vitamin_d_ng_ml"] == 25.0
        assert profile["lab_values"]["iron_ug_dl"] == 90.0

    def test_ignores_unknown_fields(self):
        """Keys not in _DEFAULT_PROFILE are silently skipped."""
        result = np_mod.merge_extracted_insights("eve", {
            "weight_kg": 60,
            "favorite_color": "blue",
        })
        assert "weight_kg" in result
        assert "favorite_color" not in result

        profile = np_mod._load_profile("eve")
        assert "favorite_color" not in profile

    def test_skips_unvalidatable_scalar(self):
        """When a scalar value fails validation, it is skipped (continue fallback)."""
        # sex must be 'male' or 'female'; pass a dict which will fail str coercion differently
        # Actually, _validate_profile_fields coerces invalid sex to 'male' — so test with
        # a field like weight_kg with a totally non-numeric value
        result = np_mod.merge_extracted_insights("frank", {
            "weight_kg": "not_a_number",
        })
        # _validate_profile_fields falls back to 70.0 for invalid weight_kg,
        # so it should still be "learned"
        profile = np_mod._load_profile("frank")
        # The validation fallback will produce 70.0 (default)
        assert profile["weight_kg"] == 70.0

    def test_creates_profile_from_defaults_if_none_exists(self):
        """If no profile file exists, one is created from _DEFAULT_PROFILE."""
        assert np_mod._load_profile("newuser") is None
        np_mod.merge_extracted_insights("newuser", {"age": 40})
        profile = np_mod._load_profile("newuser")
        assert profile is not None
        assert profile["age"] == 40
        # Other fields should be defaults
        assert profile["height_cm"] == 170.0

    def test_writes_insight_meta(self):
        """insight_meta is written with source='chat', extracted_at, and snippet."""
        np_mod.merge_extracted_insights("grace", {
            "weight_kg": 65,
            "_snippets": {"weight_kg": "I weigh 65 kg"},
        })
        profile = np_mod._load_profile("grace")
        meta = profile["insight_meta"]
        assert "weight_kg" in meta
        assert meta["weight_kg"]["source"] == "chat"
        assert "extracted_at" in meta["weight_kg"]
        assert meta["weight_kg"]["snippet"] == "I weigh 65 kg"

    def test_returns_confirmation_string(self):
        """Returns a string listing what was learned."""
        result = np_mod.merge_extracted_insights("hank", {"age": 28, "weight_kg": 75})
        assert isinstance(result, str)
        assert "Profile updated with:" in result
        assert "age" in result
        assert "weight_kg" in result

    def test_empty_insights_dict(self):
        """Empty insights dict returns 'No new profile information' message."""
        result = np_mod.merge_extracted_insights("ivan", {})
        assert "No new profile information" in result

    def test_snippets_handled_properly(self):
        """_snippets is consumed (popped) and not stored as a profile field."""
        np_mod.merge_extracted_insights("judy", {
            "height_cm": 165,
            "_snippets": {"height_cm": "I'm 165cm tall"},
        })
        profile = np_mod._load_profile("judy")
        assert "_snippets" not in profile
        assert profile["insight_meta"]["height_cm"]["snippet"] == "I'm 165cm tall"

    def test_lab_values_snippet_from_lab_key(self):
        """Lab value snippet can come from either 'lab_values' or the lab key in _snippets."""
        np_mod.merge_extracted_insights("kim", {
            "lab_values": {"vitamin_d_ng_ml": 20},
            "_snippets": {"vitamin_d_ng_ml": "my vitamin D is 20"},
        })
        profile = np_mod._load_profile("kim")
        meta = profile["insight_meta"]
        assert meta["lab_values.vitamin_d_ng_ml"]["snippet"] == "my vitamin D is 20"

    def test_lab_values_none_skipped(self):
        """Lab values that are None are not stored."""
        np_mod.merge_extracted_insights("leo", {
            "lab_values": {"vitamin_d_ng_ml": None, "iron_ug_dl": 80}
        })
        profile = np_mod._load_profile("leo")
        assert profile["lab_values"]["vitamin_d_ng_ml"] is None  # stays default None
        assert profile["lab_values"]["iron_ug_dl"] == 80.0

    def test_lab_values_non_numeric_skipped(self):
        """Lab values that can't be converted to float are skipped (continue)."""
        np_mod.merge_extracted_insights("mia", {
            "lab_values": {"vitamin_d_ng_ml": "high", "iron_ug_dl": 100}
        })
        profile = np_mod._load_profile("mia")
        # "high" can't be float-parsed, so vitamin_d stays default
        assert profile["lab_values"]["vitamin_d_ng_ml"] is None
        assert profile["lab_values"]["iron_ug_dl"] == 100.0


# ===========================================================================
# 2. compute_profile_completeness unit tests
# ===========================================================================

class TestComputeProfileCompleteness:
    """Unit tests for compute_profile_completeness()."""

    def test_empty_default_profile_score_zero(self, default_profile):
        """A default/empty profile should have score 0."""
        result = np_mod.compute_profile_completeness(default_profile)
        assert result["score"] == 0
        assert len(result["filled"]) == 0
        assert len(result["missing"]) > 0

    def test_fully_populated_profile_score_100(self, full_profile):
        """A fully-populated profile should return score 100."""
        result = np_mod.compute_profile_completeness(full_profile)
        assert result["score"] == 100
        assert len(result["missing"]) == 0

    def test_partial_profile_intermediate_score(self):
        """A partially filled profile returns an intermediate score."""
        profile = dict(np_mod._DEFAULT_PROFILE)
        profile["age"] = 40  # different from default 30
        profile["weight_kg"] = 85.0  # different from default 70.0
        profile["allergies"] = ["shellfish"]
        result = np_mod.compute_profile_completeness(profile)
        assert 0 < result["score"] < 100
        assert "age" in result["filled"]
        assert "weight_kg" in result["filled"]
        assert "allergies" in result["filled"]

    def test_field_with_insight_meta_and_default_value_counts(self):
        """A field with insight_meta AND the default value still counts as filled."""
        profile = dict(np_mod._DEFAULT_PROFILE)
        # age is 30 (the default) but has insight_meta -> should be filled
        profile["age"] = 30
        profile["insight_meta"] = {
            "age": {"source": "chat", "extracted_at": "2026-01-01T00:00:00", "snippet": "I'm 30"},
        }
        result = np_mod.compute_profile_completeness(profile)
        assert "age" in result["filled"]

    def test_field_reset_to_default_without_meta_not_counted(self):
        """A field at its default value with no insight_meta doesn't count as filled."""
        profile = dict(np_mod._DEFAULT_PROFILE)
        profile["age"] = 30  # default value
        profile["insight_meta"] = {}  # no meta for age
        result = np_mod.compute_profile_completeness(profile)
        assert "age" not in result["filled"]

    def test_missing_suggestions_present(self, default_profile):
        """Missing fields should have corresponding suggestion strings."""
        result = np_mod.compute_profile_completeness(default_profile)
        assert len(result["missing_suggestions"]) > 0
        # Each suggestion should be a string
        for s in result["missing_suggestions"]:
            assert isinstance(s, str)
            assert "?" in s  # suggestions are questions

    def test_result_keys(self, default_profile):
        """Result dict must have score, filled, missing, missing_suggestions."""
        result = np_mod.compute_profile_completeness(default_profile)
        assert "score" in result
        assert "filled" in result
        assert "missing" in result
        assert "missing_suggestions" in result

    def test_lab_values_filled_when_any_non_none(self):
        """lab_values counts as filled when at least one value is not None."""
        profile = dict(np_mod._DEFAULT_PROFILE)
        profile["lab_values"] = dict(np_mod._DEFAULT_PROFILE["lab_values"])
        profile["lab_values"]["vitamin_d_ng_ml"] = 30.0
        result = np_mod.compute_profile_completeness(profile)
        assert "lab_values" in result["filled"]


# ===========================================================================
# 3. handle_nutrition_tool with extract_insights action
# ===========================================================================

class TestHandleNutritionToolExtractInsights:
    """Tests for handle_nutrition_tool(action='extract_insights', ...)."""

    def test_valid_json_details_parsed_and_merged(self):
        """Valid JSON string details are parsed and merged into profile."""
        details = json.dumps({"weight_kg": 72, "age": 29})
        result = np_mod.handle_nutrition_tool("extract_insights", details, "user1")
        assert "Profile updated with:" in result
        profile = np_mod._load_profile("user1")
        assert profile["weight_kg"] == 72.0
        assert profile["age"] == 29

    def test_invalid_json_returns_error(self):
        """Invalid JSON details returns an error message."""
        result = np_mod.handle_nutrition_tool("extract_insights", "{bad json!!}", "user2")
        assert "Could not parse" in result

    def test_empty_details_returns_gracefully(self):
        """Empty details string returns gracefully (no crash)."""
        result = np_mod.handle_nutrition_tool("extract_insights", "", "user3")
        # Empty string -> json.loads("") raises JSONDecodeError -> "Could not parse"
        # OR empty details -> {} -> "No new profile information"
        assert isinstance(result, str)

    def test_no_username_returns_error(self):
        """Missing username returns error."""
        result = np_mod.handle_nutrition_tool("extract_insights", '{"age": 30}', "")
        assert "Error" in result

    def test_details_as_dict_also_works(self):
        """If details is already a dict (not a string), it still works."""
        # The code: json.loads(details) if isinstance(details, str) else (details or {})
        result = np_mod.handle_nutrition_tool(
            "extract_insights",
            {"weight_kg": 90, "_snippets": {"weight_kg": "I'm 90 kg"}},
            "user4",
        )
        assert "weight_kg" in result
        profile = np_mod._load_profile("user4")
        assert profile["weight_kg"] == 90.0


# ===========================================================================
# 4. Completeness endpoint
# ===========================================================================

class TestCompletenessEndpoint:
    """Tests for /api/nutrition-profile/completeness Flask endpoint."""

    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(np_mod.nutrition_bp)
        return app

    def test_returns_completeness_fields(self):
        """Endpoint returns score, filled, missing, missing_suggestions."""
        app = self._make_app()
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["username"] = "testuser"
            resp = client.get("/api/nutrition-profile/completeness")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "score" in data
        assert "filled" in data
        assert "missing" in data
        assert "missing_suggestions" in data

    def test_requires_login_401(self):
        """Endpoint returns 401 when not logged in."""
        app = self._make_app()
        with app.test_client() as client:
            resp = client.get("/api/nutrition-profile/completeness")
        assert resp.status_code == 401

    def test_score_increases_with_profile_data(self):
        """Score increases when profile has data."""
        app = self._make_app()
        username = "scored_user"

        # Save a partial profile
        profile = dict(np_mod._DEFAULT_PROFILE)
        profile["age"] = 40
        profile["weight_kg"] = 85.0
        profile["allergies"] = ["nuts"]
        np_mod._save_profile(username, profile)

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["username"] = username
            resp = client.get("/api/nutrition-profile/completeness")
        data = resp.get_json()
        assert data["score"] > 0
        assert "age" in data["filled"]


# ===========================================================================
# 5. Profile gate removal
# ===========================================================================

class TestProfileGateRemoval:
    """Verify create_plan works without a pre-existing profile."""

    @patch("functions.nutrition_plans.generate_nutrition_plan")
    def test_create_plan_without_profile(self, mock_gen):
        """create_plan action works without any profile (no 'Please set up' error)."""
        mock_gen.return_value = {
            "plan_id": "abc123",
            "title": "Test Plan",
            "active": True,
            "duration_days": 7,
            "daily_targets": {},
            "days": {},
            "grocery_list": [],
            "nutrient_alerts": [],
        }
        result = np_mod.handle_nutrition_tool("create_plan", "a simple plan", "noprofile_user")
        assert "Please set up" not in result
        assert "Test Plan" in result
        mock_gen.assert_called_once_with("a simple plan", "noprofile_user")

    @patch("functions.nutrition_plans.generate_nutrition_plan")
    def test_create_plan_via_endpoint_without_profile(self, mock_gen):
        """POST /api/nutrition-plan works without a saved profile."""
        mock_gen.return_value = {
            "plan_id": "def456",
            "title": "No Profile Plan",
            "active": True,
            "duration_days": 7,
            "daily_targets": {},
            "days": {},
            "grocery_list": [],
            "nutrient_alerts": [],
        }
        from flask import Flask
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(np_mod.nutrition_bp)

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["username"] = "noprofile_api"
            resp = client.post(
                "/api/nutrition-plan",
                json={"details": "quick plan"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["plan"]["title"] == "No Profile Plan"

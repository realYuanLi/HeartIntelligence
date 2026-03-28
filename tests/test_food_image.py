"""Tests for the food image calorie estimation feature."""

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
if not _init_path.exists():
    _init_path.touch()

import functions.food_image_analyzer as fia


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FOOD_RESPONSE = json.dumps({
    "detected": True,
    "items": [
        {
            "name": "Grilled Chicken Breast",
            "estimated_portion": "150g",
            "calories": 248,
            "protein_g": 46.0,
            "carbs_g": 0.0,
            "fat_g": 5.4,
            "fiber_g": 0.0,
            "confidence": "high",
        },
        {
            "name": "Brown Rice",
            "estimated_portion": "1 cup",
            "calories": 216,
            "protein_g": 5.0,
            "carbs_g": 45.0,
            "fat_g": 1.8,
            "fiber_g": 3.5,
            "confidence": "medium",
        },
        {
            "name": "Steamed Broccoli",
            "estimated_portion": "1 cup",
            "calories": 55,
            "protein_g": 3.7,
            "carbs_g": 11.0,
            "fat_g": 0.6,
            "fiber_g": 5.1,
            "confidence": "high",
        },
    ],
})

NON_FOOD_RESPONSE = json.dumps({
    "detected": False,
    "items": [],
})

SAMPLE_DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="

SAMPLE_PROFILE = {
    "age": 30,
    "weight_kg": 75.0,
    "height_cm": 178.0,
    "sex": "male",
    "activity_level": "moderate",
    "health_goals": [],
    "allergies": [],
    "dietary_preferences": [],
    "lab_values": {},
}


def _make_openai_response(content: str) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ---------------------------------------------------------------------------
# Tests: analyze_food_image
# ---------------------------------------------------------------------------

class TestAnalyzeFoodImage:
    """Tests for the analyze_food_image function."""

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_food_detected(self, mock_create):
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is True
        assert len(result["items"]) == 3
        assert result["items"][0]["name"] == "Grilled Chicken Breast"
        assert result["items"][0]["calories"] == 248
        assert result["meal_total"]["calories"] == 248 + 216 + 55
        assert result["profile_comparison"] is None  # no username
        assert isinstance(result["suggestions"], list)

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_non_food_image(self, mock_create):
        mock_create.return_value = _make_openai_response(NON_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is False
        assert result["items"] == []

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_no_username_means_no_profile_comparison(self, mock_create):
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI, username="")

        assert result["detected"] is True
        assert result["profile_comparison"] is None

    @patch("functions.nutrition_plans._load_profile", return_value=SAMPLE_PROFILE)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_with_username_loads_profile(self, mock_create, mock_load):
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)

        # Mock compute_daily_targets to avoid loading RDA files
        with patch("functions.nutrition_search.compute_daily_targets") as mock_targets:
            mock_targets.return_value = {
                "calories": 2500,
                "protein_g": 120.0,
                "carbs_g": 300.0,
                "fat_g": 83.0,
                "fiber_g": 30.0,
            }
            result = fia.analyze_food_image(SAMPLE_DATA_URI, username="testuser")

        assert result["detected"] is True
        assert result["profile_comparison"] is not None
        assert result["profile_comparison"]["daily_target_calories"] == 2500
        mock_load.assert_called_once_with("testuser")

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_malformed_json_response(self, mock_create):
        mock_create.return_value = _make_openai_response("This is not JSON at all")
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is False
        assert "error" in result

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_json_with_code_fences(self, mock_create):
        fenced = f"```json\n{SAMPLE_FOOD_RESPONSE}\n```"
        mock_create.return_value = _make_openai_response(fenced)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is True
        assert len(result["items"]) == 3

    def test_unsupported_mimetype(self):
        bmp_uri = "data:image/bmp;base64,Qk0="
        result = fia.analyze_food_image(bmp_uri)

        assert result["detected"] is False
        assert "Unsupported image type" in result.get("error", "")

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_api_exception_handled_generic_message(self, mock_create):
        """Generic errors must NOT leak raw exception details to the user."""
        mock_create.side_effect = Exception("API timeout")
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is False
        assert "error" in result
        # Implementation should return a user-friendly message, not the raw exception
        assert "Unable to analyze" in result["error"]
        assert "API timeout" not in result["error"]


# ---------------------------------------------------------------------------
# Tests: profile comparison math
# ---------------------------------------------------------------------------

class TestProfileComparison:
    """Tests for the _compute_profile_comparison helper."""

    def test_basic_comparison(self):
        meal_total = {
            "calories": 500,
            "protein_g": 40.0,
            "carbs_g": 50.0,
            "fat_g": 15.0,
            "fiber_g": 8.0,
        }
        profile = {
            "age": 30,
            "weight_kg": 75.0,
            "height_cm": 178.0,
            "sex": "male",
            "activity_level": "moderate",
            "health_goals": [],
        }
        with patch("functions.nutrition_search.compute_daily_targets") as mock_targets:
            mock_targets.return_value = {
                "calories": 2500,
                "protein_g": 120.0,
                "carbs_g": 300.0,
                "fat_g": 83.0,
                "fiber_g": 30.0,
            }
            result = fia._compute_profile_comparison(meal_total, profile)

        assert result["daily_target_calories"] == 2500
        assert result["remaining_calories"] == 2000
        assert result["protein_pct_of_target"] == pytest.approx(33.3, abs=0.1)
        assert result["carbs_pct_of_target"] == pytest.approx(16.7, abs=0.1)
        assert result["fat_pct_of_target"] == pytest.approx(18.1, abs=0.1)

    def test_remaining_calories_floors_at_zero(self):
        meal_total = {
            "calories": 3000,
            "protein_g": 100.0,
            "carbs_g": 300.0,
            "fat_g": 100.0,
            "fiber_g": 10.0,
        }
        with patch("functions.nutrition_search.compute_daily_targets") as mock_targets:
            mock_targets.return_value = {
                "calories": 2000,
                "protein_g": 100.0,
                "carbs_g": 250.0,
                "fat_g": 67.0,
                "fiber_g": 25.0,
            }
            result = fia._compute_profile_comparison(meal_total, {"age": 30})

        assert result["remaining_calories"] == 0


# ---------------------------------------------------------------------------
# Tests: meal total computation
# ---------------------------------------------------------------------------

class TestMealTotal:
    """Tests for the _compute_meal_total helper."""

    def test_sum_multiple_items(self):
        items = [
            {"calories": 200, "protein_g": 20.0, "carbs_g": 10.0, "fat_g": 5.0, "fiber_g": 2.0},
            {"calories": 300, "protein_g": 10.0, "carbs_g": 40.0, "fat_g": 8.0, "fiber_g": 4.0},
        ]
        result = fia._compute_meal_total(items)
        assert result["calories"] == 500
        assert result["protein_g"] == 30.0
        assert result["carbs_g"] == 50.0
        assert result["fat_g"] == 13.0
        assert result["fiber_g"] == 6.0

    def test_empty_items(self):
        result = fia._compute_meal_total([])
        assert result["calories"] == 0
        assert result["protein_g"] == 0.0


# ---------------------------------------------------------------------------
# Tests: format_food_image_analysis
# ---------------------------------------------------------------------------

class TestFormatFoodImageAnalysis:
    """Tests for the format_food_image_analysis function."""

    def test_renders_item_breakdown(self):
        analysis = {
            "detected": True,
            "items": [
                {
                    "name": "Pasta",
                    "estimated_portion": "1 cup",
                    "calories": 220,
                    "protein_g": 8.0,
                    "carbs_g": 43.0,
                    "fat_g": 1.3,
                    "fiber_g": 2.5,
                    "confidence": "high",
                },
            ],
            "meal_total": {"calories": 220, "protein_g": 8.0, "carbs_g": 43.0, "fat_g": 1.3, "fiber_g": 2.5},
            "profile_comparison": None,
            "suggestions": ["Consider adding a protein source to make this meal more balanced."],
        }
        output = fia.format_food_image_analysis(analysis)

        assert "**Food Analysis**" in output
        assert "**Pasta**" in output
        assert "1 cup" in output
        assert "220 kcal" in output
        assert "**Meal Total:**" in output
        assert "**Suggestions:**" in output
        assert "protein source" in output

    def test_renders_profile_comparison(self):
        analysis = {
            "detected": True,
            "items": [
                {
                    "name": "Salad",
                    "estimated_portion": "1 bowl",
                    "calories": 150,
                    "protein_g": 5.0,
                    "carbs_g": 20.0,
                    "fat_g": 6.0,
                    "fiber_g": 4.0,
                    "confidence": "medium",
                },
            ],
            "meal_total": {"calories": 150, "protein_g": 5.0, "carbs_g": 20.0, "fat_g": 6.0, "fiber_g": 4.0},
            "profile_comparison": {
                "daily_target_calories": 2000,
                "remaining_calories": 1850,
                "protein_pct_of_target": 4.2,
                "carbs_pct_of_target": 6.7,
                "fat_pct_of_target": 9.0,
            },
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)

        assert "**Daily Budget:**" in output
        assert "1850 kcal remaining" in output
        assert "2000 kcal target" in output

    def test_not_detected_returns_empty(self):
        analysis = {"detected": False, "items": []}
        output = fia.format_food_image_analysis(analysis)
        assert output == ""

    def test_error_returned_on_failure(self):
        analysis = {"detected": False, "items": [], "error": "Something broke"}
        output = fia.format_food_image_analysis(analysis)
        assert "Something broke" in output

    def test_confidence_icons(self):
        analysis = {
            "detected": True,
            "items": [
                {
                    "name": "Mystery Food",
                    "estimated_portion": "1 piece",
                    "calories": 100,
                    "protein_g": 5.0,
                    "carbs_g": 10.0,
                    "fat_g": 3.0,
                    "fiber_g": 1.0,
                    "confidence": "low",
                },
            ],
            "meal_total": {"calories": 100, "protein_g": 5.0, "carbs_g": 10.0, "fat_g": 3.0, "fiber_g": 1.0},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[?]" in output  # low confidence icon


# ---------------------------------------------------------------------------
# Tests: suggestions
# ---------------------------------------------------------------------------

class TestSuggestions:
    """Tests for the _generate_suggestions helper."""

    def test_low_fiber_suggestion(self):
        meal_total = {"calories": 500, "protein_g": 30.0, "carbs_g": 50.0, "fat_g": 15.0, "fiber_g": 1.0}
        items = [{"name": "Burger", "confidence": "high"}]
        result = fia._generate_suggestions(meal_total, None, items)
        assert any("fiber" in s.lower() for s in result)

    def test_low_confidence_items_noted(self):
        meal_total = {"calories": 400, "protein_g": 20.0, "carbs_g": 40.0, "fat_g": 10.0, "fiber_g": 5.0}
        items = [{"name": "Unknown Stew", "confidence": "low"}]
        result = fia._generate_suggestions(meal_total, None, items)
        assert any("Unknown Stew" in s for s in result)

    def test_no_suggestions_for_empty_items(self):
        meal_total = {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0}
        result = fia._generate_suggestions(meal_total, None, [])
        assert result == []

    def test_high_calorie_meal_warning(self):
        meal_total = {"calories": 1500, "protein_g": 50.0, "carbs_g": 150.0, "fat_g": 60.0, "fiber_g": 8.0}
        profile_comparison = {
            "daily_target_calories": 2000,
            "remaining_calories": 500,
            "protein_pct_of_target": 41.7,
            "carbs_pct_of_target": 50.0,
            "fat_pct_of_target": 89.6,
        }
        items = [{"name": "Large Pizza", "confidence": "high"}]
        result = fia._generate_suggestions(meal_total, profile_comparison, items)
        assert any("75%" in s for s in result)
        assert any("fat" in s.lower() for s in result)


# ---------------------------------------------------------------------------
# Tests: mimetype extraction
# ---------------------------------------------------------------------------

class TestMimetype:
    """Tests for _extract_mimetype."""

    def test_jpeg(self):
        assert fia._extract_mimetype("data:image/jpeg;base64,abc") == "image/jpeg"

    def test_png(self):
        assert fia._extract_mimetype("data:image/png;base64,abc") == "image/png"

    def test_no_match(self):
        assert fia._extract_mimetype("not-a-data-uri") is None

    def test_webp(self):
        assert fia._extract_mimetype("data:image/webp;base64,abc") == "image/webp"

    def test_gif(self):
        assert fia._extract_mimetype("data:image/gif;base64,abc") == "image/gif"

    def test_empty_string(self):
        assert fia._extract_mimetype("") is None

    def test_non_image_data_uri(self):
        assert fia._extract_mimetype("data:text/plain;base64,abc") is None


# ---------------------------------------------------------------------------
# Tests: None mimetype (garbage / non-data-URI input)
# ---------------------------------------------------------------------------

class TestUnsupportedMimetypeEdgeCases:
    """Edge cases for mimetype validation inside analyze_food_image."""

    def test_none_mimetype_from_garbage_input(self):
        """When _extract_mimetype returns None, the error message should be safe."""
        result = fia.analyze_food_image("totally-not-a-data-uri")
        assert result["detected"] is False
        assert "Unsupported image type" in result.get("error", "")
        assert "None" in result["error"]  # mimetype is None

    def test_gif_is_supported(self):
        """GIF should pass mimetype validation."""
        gif_uri = "data:image/gif;base64,R0lGODlhAQABAIAAAP8AAP8AAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
        with patch("functions.food_image_analyzer.openai.chat.completions.create") as mock_create:
            mock_create.return_value = _make_openai_response(NON_FOOD_RESPONSE)
            result = fia.analyze_food_image(gif_uri)
        # Should reach the vision API, not be rejected at mimetype check
        assert "Unsupported image type" not in result.get("error", "")

    def test_svg_is_unsupported(self):
        svg_uri = "data:image/svg+xml;base64,PHN2Zz4="
        result = fia.analyze_food_image(svg_uri)
        assert result["detected"] is False
        assert "Unsupported image type" in result.get("error", "")


# ---------------------------------------------------------------------------
# Tests: vision model returns unexpected shapes
# ---------------------------------------------------------------------------

class TestVisionResponseEdgeCases:
    """Edge cases for the vision model response parsing."""

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_vision_returns_json_array(self, mock_create):
        """Non-dict JSON (e.g. a list) should return an error, not crash."""
        mock_create.return_value = _make_openai_response('[{"name": "pasta"}]')
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is False
        assert "non-object" in result.get("error", "").lower()

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_vision_returns_empty_content(self, mock_create):
        """Empty string from the model should trigger JSONDecodeError handler."""
        mock_create.return_value = _make_openai_response("")
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is False
        assert "error" in result

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_vision_returns_none_content(self, mock_create):
        """None .content should be treated as empty string."""
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is False

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_detected_true_but_items_empty(self, mock_create):
        """detected=True with empty items list should be treated as not-detected."""
        mock_create.return_value = _make_openai_response(
            json.dumps({"detected": True, "items": []})
        )
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is False
        assert result["items"] == []
        assert result["meal_total"]["calories"] == 0

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_json_with_plain_code_fences(self, mock_create):
        """Code fences without 'json' language tag should still be stripped."""
        fenced = f"```\n{SAMPLE_FOOD_RESPONSE}\n```"
        mock_create.return_value = _make_openai_response(fenced)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is True
        assert len(result["items"]) == 3

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_json_decode_error_returns_generic_message(self, mock_create):
        """JSONDecodeError should give a user-friendly error, not a traceback."""
        mock_create.return_value = _make_openai_response("{invalid json::")
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is False
        assert "Unable to analyze" in result["error"]
        # Must not contain internal details
        assert "JSONDecodeError" not in result["error"]


# ---------------------------------------------------------------------------
# Tests: item sanitization
# ---------------------------------------------------------------------------

class TestItemSanitization:
    """Tests that partial / malformed items from the vision model are safely sanitized."""

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_missing_fields_get_defaults(self, mock_create):
        """An item with missing fields should get safe defaults."""
        sparse_response = json.dumps({
            "detected": True,
            "items": [{"name": "Mystery"}],  # all other fields missing
        })
        mock_create.return_value = _make_openai_response(sparse_response)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is True
        item = result["items"][0]
        assert item["name"] == "Mystery"
        assert item["estimated_portion"] == "1 serving"
        assert item["calories"] == 0
        assert item["protein_g"] == 0.0
        assert item["carbs_g"] == 0.0
        assert item["fat_g"] == 0.0
        assert item["fiber_g"] == 0.0
        assert item["confidence"] == "medium"

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_completely_empty_item(self, mock_create):
        """An empty dict item should still produce a sanitized entry."""
        mock_create.return_value = _make_openai_response(
            json.dumps({"detected": True, "items": [{}]})
        )
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is True
        item = result["items"][0]
        assert item["name"] == "Unknown"

    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_float_precision_is_rounded(self, mock_create):
        """Nutrient floats should be rounded to 1 decimal place."""
        response = json.dumps({
            "detected": True,
            "items": [{
                "name": "Test",
                "calories": 100,
                "protein_g": 12.456,
                "carbs_g": 33.999,
                "fat_g": 5.111,
                "fiber_g": 2.789,
            }],
        })
        mock_create.return_value = _make_openai_response(response)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        item = result["items"][0]
        assert item["protein_g"] == 12.5
        assert item["carbs_g"] == 34.0
        assert item["fat_g"] == 5.1
        assert item["fiber_g"] == 2.8


# ---------------------------------------------------------------------------
# Tests: profile comparison edge cases
# ---------------------------------------------------------------------------

class TestProfileComparisonEdgeCases:
    """Edge cases for _compute_profile_comparison."""

    def test_zero_calorie_target(self):
        """If compute_daily_targets returns 0 calories, remaining should be 0, not negative."""
        meal_total = {
            "calories": 500, "protein_g": 20.0, "carbs_g": 40.0, "fat_g": 10.0, "fiber_g": 5.0,
        }
        with patch("functions.nutrition_search.compute_daily_targets") as mock_targets:
            mock_targets.return_value = {
                "calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0,
            }
            result = fia._compute_profile_comparison(meal_total, {"age": 30})

        assert result["remaining_calories"] == 0
        assert result["protein_pct_of_target"] == 0.0
        assert result["carbs_pct_of_target"] == 0.0
        assert result["fat_pct_of_target"] == 0.0

    def test_exact_calorie_match(self):
        """Meal exactly equals target => remaining = 0."""
        meal_total = {
            "calories": 2000, "protein_g": 100.0, "carbs_g": 250.0, "fat_g": 67.0, "fiber_g": 25.0,
        }
        with patch("functions.nutrition_search.compute_daily_targets") as mock_targets:
            mock_targets.return_value = {
                "calories": 2000, "protein_g": 100.0, "carbs_g": 250.0, "fat_g": 67.0, "fiber_g": 25.0,
            }
            result = fia._compute_profile_comparison(meal_total, {"age": 30})

        assert result["remaining_calories"] == 0
        assert result["protein_pct_of_target"] == 100.0

    def test_negative_target_returns_zero_pct(self):
        """Negative target values (defensive) should return 0% not crash."""
        meal_total = {
            "calories": 500, "protein_g": 20.0, "carbs_g": 40.0, "fat_g": 10.0, "fiber_g": 5.0,
        }
        with patch("functions.nutrition_search.compute_daily_targets") as mock_targets:
            mock_targets.return_value = {
                "calories": 2000, "protein_g": -10.0, "carbs_g": -5.0, "fat_g": -3.0, "fiber_g": 25.0,
            }
            result = fia._compute_profile_comparison(meal_total, {"age": 30})

        assert result["protein_pct_of_target"] == 0.0
        assert result["carbs_pct_of_target"] == 0.0
        assert result["fat_pct_of_target"] == 0.0


# ---------------------------------------------------------------------------
# Tests: _compute_meal_total edge cases
# ---------------------------------------------------------------------------

class TestMealTotalEdgeCases:
    """Edge cases for the _compute_meal_total helper."""

    def test_items_with_missing_keys(self):
        """Items missing some keys should use default 0."""
        items = [{"calories": 100}, {"protein_g": 10.0}]
        result = fia._compute_meal_total(items)
        assert result["calories"] == 100
        assert result["protein_g"] == 10.0
        assert result["carbs_g"] == 0.0

    def test_single_item(self):
        items = [{"calories": 350, "protein_g": 25.0, "carbs_g": 30.0, "fat_g": 12.0, "fiber_g": 3.0}]
        result = fia._compute_meal_total(items)
        assert result["calories"] == 350
        assert result["fiber_g"] == 3.0

    def test_rounding_in_totals(self):
        """Floating point accumulation should be rounded to 1 decimal."""
        items = [
            {"protein_g": 1.11, "carbs_g": 2.22, "fat_g": 3.33, "fiber_g": 4.44, "calories": 100},
            {"protein_g": 1.11, "carbs_g": 2.22, "fat_g": 3.33, "fiber_g": 4.44, "calories": 100},
            {"protein_g": 1.11, "carbs_g": 2.22, "fat_g": 3.33, "fiber_g": 4.44, "calories": 100},
        ]
        result = fia._compute_meal_total(items)
        # 3 * 1.11 = 3.33 => round(3.33, 1) = 3.3
        assert result["protein_g"] == 3.3
        assert result["carbs_g"] == 6.7  # 3 * 2.22 = 6.66 => 6.7
        assert result["fat_g"] == 10.0   # 3 * 3.33 = 9.99 => 10.0
        assert result["fiber_g"] == 13.3 # 3 * 4.44 = 13.32 => 13.3


# ---------------------------------------------------------------------------
# Tests: suggestions edge cases
# ---------------------------------------------------------------------------

class TestSuggestionsEdgeCases:
    """Additional edge cases for _generate_suggestions."""

    def test_low_protein_with_profile(self):
        """Low protein + profile present triggers protein suggestion."""
        meal_total = {"calories": 500, "protein_g": 5.0, "carbs_g": 80.0, "fat_g": 10.0, "fiber_g": 5.0}
        profile_comparison = {
            "daily_target_calories": 2000,
            "remaining_calories": 1500,
            "protein_pct_of_target": 4.0,  # < 15
            "carbs_pct_of_target": 32.0,
            "fat_pct_of_target": 15.0,
        }
        items = [{"name": "White Rice", "confidence": "high"}]
        result = fia._generate_suggestions(meal_total, profile_comparison, items)
        assert any("protein" in s.lower() for s in result)

    def test_low_protein_without_profile(self):
        """Low protein + no profile + calories > 300 triggers generic protein suggestion."""
        meal_total = {"calories": 400, "protein_g": 5.0, "carbs_g": 60.0, "fat_g": 10.0, "fiber_g": 5.0}
        items = [{"name": "Fries", "confidence": "high"}]
        result = fia._generate_suggestions(meal_total, None, items)
        assert any("protein" in s.lower() for s in result)

    def test_no_generic_protein_warning_for_small_meal(self):
        """Small meal (< 300 cal) should not trigger protein warning without profile."""
        meal_total = {"calories": 150, "protein_g": 2.0, "carbs_g": 30.0, "fat_g": 2.0, "fiber_g": 1.0}
        items = [{"name": "Apple", "confidence": "high"}]
        result = fia._generate_suggestions(meal_total, None, items)
        assert not any("protein" in s.lower() for s in result)

    def test_high_fat_suggestion_with_profile(self):
        """Fat > 50% of daily target triggers fat warning."""
        meal_total = {"calories": 800, "protein_g": 30.0, "carbs_g": 50.0, "fat_g": 45.0, "fiber_g": 5.0}
        profile_comparison = {
            "daily_target_calories": 2000,
            "remaining_calories": 1200,
            "protein_pct_of_target": 25.0,
            "carbs_pct_of_target": 20.0,
            "fat_pct_of_target": 55.0,  # > 50
        }
        items = [{"name": "Fried Chicken", "confidence": "high"}]
        result = fia._generate_suggestions(meal_total, profile_comparison, items)
        assert any("fat" in s.lower() for s in result)

    def test_multiple_low_confidence_items(self):
        """Multiple low confidence items should be listed in the suggestion."""
        meal_total = {"calories": 600, "protein_g": 25.0, "carbs_g": 60.0, "fat_g": 20.0, "fiber_g": 5.0}
        items = [
            {"name": "Soup", "confidence": "low"},
            {"name": "Bread", "confidence": "high"},
            {"name": "Mystery Sauce", "confidence": "low"},
        ]
        result = fia._generate_suggestions(meal_total, None, items)
        low_conf = [s for s in result if "hard to identify" in s]
        assert len(low_conf) == 1
        assert "Soup" in low_conf[0]
        assert "Mystery Sauce" in low_conf[0]
        assert "Bread" not in low_conf[0]


# ---------------------------------------------------------------------------
# Tests: format_food_image_analysis edge cases
# ---------------------------------------------------------------------------

class TestFormatEdgeCases:
    """Additional edge cases for format_food_image_analysis."""

    def test_high_confidence_icon(self):
        analysis = {
            "detected": True,
            "items": [
                {"name": "Apple", "estimated_portion": "1 medium", "calories": 95,
                 "protein_g": 0.5, "carbs_g": 25.0, "fat_g": 0.3, "fiber_g": 4.4, "confidence": "high"},
            ],
            "meal_total": {"calories": 95, "protein_g": 0.5, "carbs_g": 25.0, "fat_g": 0.3, "fiber_g": 4.4},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[+]" in output

    def test_medium_confidence_icon(self):
        analysis = {
            "detected": True,
            "items": [
                {"name": "Soup", "estimated_portion": "1 bowl", "calories": 200,
                 "protein_g": 8.0, "carbs_g": 20.0, "fat_g": 10.0, "fiber_g": 3.0, "confidence": "medium"},
            ],
            "meal_total": {"calories": 200, "protein_g": 8.0, "carbs_g": 20.0, "fat_g": 10.0, "fiber_g": 3.0},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[~]" in output

    def test_unknown_confidence_defaults_to_tilde(self):
        analysis = {
            "detected": True,
            "items": [
                {"name": "Thing", "estimated_portion": "1", "calories": 50,
                 "protein_g": 1.0, "carbs_g": 5.0, "fat_g": 1.0, "fiber_g": 0.5, "confidence": "INVALID"},
            ],
            "meal_total": {"calories": 50, "protein_g": 1.0, "carbs_g": 5.0, "fat_g": 1.0, "fiber_g": 0.5},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[~]" in output

    def test_no_suggestions_section_when_empty(self):
        analysis = {
            "detected": True,
            "items": [
                {"name": "Salad", "estimated_portion": "1 bowl", "calories": 150,
                 "protein_g": 5.0, "carbs_g": 20.0, "fat_g": 6.0, "fiber_g": 4.0, "confidence": "high"},
            ],
            "meal_total": {"calories": 150, "protein_g": 5.0, "carbs_g": 20.0, "fat_g": 6.0, "fiber_g": 4.0},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "**Suggestions:**" not in output

    def test_multiple_items_all_rendered(self):
        analysis = {
            "detected": True,
            "items": [
                {"name": "Rice", "estimated_portion": "1 cup", "calories": 200,
                 "protein_g": 4.0, "carbs_g": 45.0, "fat_g": 0.4, "fiber_g": 0.6, "confidence": "high"},
                {"name": "Chicken", "estimated_portion": "150g", "calories": 250,
                 "protein_g": 46.0, "carbs_g": 0.0, "fat_g": 5.4, "fiber_g": 0.0, "confidence": "high"},
            ],
            "meal_total": {"calories": 450, "protein_g": 50.0, "carbs_g": 45.0, "fat_g": 5.8, "fiber_g": 0.6},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "**Rice**" in output
        assert "**Chicken**" in output
        assert "450 kcal" in output


# ---------------------------------------------------------------------------
# Tests: profile loading when username yields no profile
# ---------------------------------------------------------------------------

class TestProfileLoadingEdgeCases:
    """Test analyze_food_image when username is given but no profile exists."""

    @patch("functions.nutrition_plans._load_profile", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_username_but_no_profile(self, mock_create, mock_load):
        """When profile doesn't exist, profile_comparison should be None."""
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI, username="ghost_user")

        assert result["detected"] is True
        assert result["profile_comparison"] is None
        mock_load.assert_called_once_with("ghost_user")


# ---------------------------------------------------------------------------
# Tests: skill runtime gate (_should_run) for food_image_analysis
# ---------------------------------------------------------------------------

class TestSkillRuntimeFoodImageGate:
    """Tests for the _should_run gate and _run_food_image_analysis in SkillRuntime."""

    def _make_skill(self):
        """Create a minimal SkillDefinition for food_image_analysis."""
        from functions.skills_runtime import SkillDefinition
        return SkillDefinition(
            skill_id="food_image_analysis",
            title="Food Image Analysis",
            executor="food_image_analysis",
            kind="context",
            enabled_by_default=True,
            description="Analyze food images",
            instructions="",
        )

    @patch("functions.skills_runtime.analyze_health_query_with_raw_data", return_value=(False, None, None, None))
    def test_should_run_with_images(self, _mock_health):
        from functions.skills_runtime import SkillRuntime
        rt = SkillRuntime.__new__(SkillRuntime)
        rt.ehr_data = {}
        rt.mobile_data = {}
        skill = self._make_skill()
        assert rt._should_run(skill, "what is this", {"images": [SAMPLE_DATA_URI]}) is True

    @patch("functions.skills_runtime.analyze_health_query_with_raw_data", return_value=(False, None, None, None))
    def test_should_run_without_images(self, _mock_health):
        from functions.skills_runtime import SkillRuntime
        rt = SkillRuntime.__new__(SkillRuntime)
        rt.ehr_data = {}
        rt.mobile_data = {}
        skill = self._make_skill()
        assert rt._should_run(skill, "what is this", {}) is False

    @patch("functions.skills_runtime.analyze_health_query_with_raw_data", return_value=(False, None, None, None))
    def test_should_run_with_empty_images_list(self, _mock_health):
        from functions.skills_runtime import SkillRuntime
        rt = SkillRuntime.__new__(SkillRuntime)
        rt.ehr_data = {}
        rt.mobile_data = {}
        skill = self._make_skill()
        assert rt._should_run(skill, "analyze", {"images": []}) is False

    @patch("functions.skills_runtime.analyze_health_query_with_raw_data", return_value=(False, None, None, None))
    def test_should_run_with_no_context(self, _mock_health):
        from functions.skills_runtime import SkillRuntime
        rt = SkillRuntime.__new__(SkillRuntime)
        rt.ehr_data = {}
        rt.mobile_data = {}
        skill = self._make_skill()
        assert rt._should_run(skill, "analyze", None) is False


# ---------------------------------------------------------------------------
# Tests: _run_food_image_analysis executor
# ---------------------------------------------------------------------------

class TestRunFoodImageAnalysisExecutor:
    """Tests for the _run_food_image_analysis method in SkillRuntime."""

    def _make_runtime(self):
        from functions.skills_runtime import SkillRuntime, SkillDefinition
        rt = SkillRuntime.__new__(SkillRuntime)
        rt.ehr_data = {}
        rt.mobile_data = {}
        return rt

    def _make_skill(self):
        from functions.skills_runtime import SkillDefinition
        return SkillDefinition(
            skill_id="food_image_analysis",
            title="Food Image Analysis",
            executor="food_image_analysis",
            kind="context",
            enabled_by_default=True,
            description="Analyze food images",
            instructions="",
        )

    @patch("functions.skills_runtime.analyze_food_image")
    @patch("functions.skills_runtime.format_food_image_analysis")
    def test_executor_activated(self, mock_format, mock_analyze):
        mock_analyze.return_value = {"detected": True, "items": [{"name": "Pasta"}]}
        mock_format.return_value = "**Food Analysis**\n..."
        rt = self._make_runtime()
        result = rt._run_food_image_analysis(
            "what is this",
            {"images": [SAMPLE_DATA_URI], "user": "alice"},
            None,
            self._make_skill(),
        )
        assert result["activated"] is True
        assert "food_image_summary" in result
        mock_analyze.assert_called_once_with(SAMPLE_DATA_URI, username="alice")

    @patch("functions.skills_runtime.analyze_food_image")
    def test_executor_not_detected(self, mock_analyze):
        mock_analyze.return_value = {"detected": False, "items": []}
        rt = self._make_runtime()
        result = rt._run_food_image_analysis(
            "what is this",
            {"images": [SAMPLE_DATA_URI], "user": "alice"},
            None,
            self._make_skill(),
        )
        assert result["activated"] is False

    def test_executor_no_images(self):
        rt = self._make_runtime()
        result = rt._run_food_image_analysis(
            "what is this",
            {"images": [], "user": "alice"},
            None,
            self._make_skill(),
        )
        assert result["activated"] is False

    @patch("functions.skills_runtime.analyze_food_image")
    @patch("functions.skills_runtime.format_food_image_analysis")
    def test_executor_calls_status_updater(self, mock_format, mock_analyze):
        mock_analyze.return_value = {"detected": True, "items": [{"name": "Egg"}]}
        mock_format.return_value = "**Food Analysis**"
        rt = self._make_runtime()
        status_cb = MagicMock()
        rt._run_food_image_analysis(
            "what is this",
            {"images": [SAMPLE_DATA_URI], "user": ""},
            status_cb,
            self._make_skill(),
        )
        status_cb.assert_called_once_with("analyzing_food_image")

    @patch("functions.skills_runtime.analyze_food_image")
    def test_executor_uses_first_image_only(self, mock_analyze):
        """When multiple images are provided, only the first should be analyzed."""
        mock_analyze.return_value = {"detected": False, "items": []}
        rt = self._make_runtime()
        rt._run_food_image_analysis(
            "analyze",
            {"images": ["data:image/png;base64,aaa", "data:image/png;base64,bbb"], "user": ""},
            None,
            self._make_skill(),
        )
        mock_analyze.assert_called_once_with("data:image/png;base64,aaa", username="")


# ---------------------------------------------------------------------------
# Tests: Agent image extraction (openai_reply)
# ---------------------------------------------------------------------------

class TestAgentImageExtraction:
    """Tests for Agent.openai_reply handling of images in messages."""

    def _make_agent(self):
        from functions.agent import Agent
        with patch("functions.skills_runtime.SkillRuntime._load_skills", return_value={}):
            return Agent(role="test", llm="gpt-4o", sys_message="You are a test agent.")

    @patch("functions.agent.openai.chat.completions.create")
    def test_image_only_message_extracts_images(self, mock_create):
        """A message with images but empty text should still pass images to skills."""
        mock_msg = MagicMock()
        mock_msg.content = "I see food."
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = self._make_agent()
        # Patch the skill_runtime.run to capture the runtime_context
        with patch.object(agent.skill_runtime, "run", return_value={}) as mock_run:
            messages = [
                {"role": "system", "content": "System. Username: testuser"},
                {"role": "user", "content": "", "images": [SAMPLE_DATA_URI]},
            ]
            agent.openai_reply(messages)

            # Verify skill_runtime.run was called with images in context
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            runtime_ctx = call_kwargs.kwargs.get("runtime_context") or call_kwargs[1].get("runtime_context")
            assert "images" in runtime_ctx
            assert runtime_ctx["images"] == [SAMPLE_DATA_URI]

    @patch("functions.agent.openai.chat.completions.create")
    def test_image_with_caption_passes_both(self, mock_create):
        """A message with images AND text should pass both to skills."""
        mock_msg = MagicMock()
        mock_msg.content = "Here's the analysis."
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = self._make_agent()
        with patch.object(agent.skill_runtime, "run", return_value={}) as mock_run:
            messages = [
                {"role": "system", "content": "System. Username: testuser"},
                {"role": "user", "content": "How many calories?", "images": [SAMPLE_DATA_URI]},
            ]
            agent.openai_reply(messages)

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # The query should be the text, not "[image]"
            assert call_kwargs[1]["query"] == "How many calories?" or call_kwargs.kwargs.get("query") == "How many calories?"

    @patch("functions.agent.openai.chat.completions.create")
    def test_image_only_message_uses_placeholder_query(self, mock_create):
        """When there is no text caption, the skill query should be '[image]'."""
        mock_msg = MagicMock()
        mock_msg.content = "Food detected."
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = self._make_agent()
        with patch.object(agent.skill_runtime, "run", return_value={}) as mock_run:
            messages = [
                {"role": "system", "content": "System. Username: testuser"},
                {"role": "user", "content": "", "images": [SAMPLE_DATA_URI]},
            ]
            agent.openai_reply(messages)

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            query = call_args.kwargs.get("query") or call_args[1].get("query")
            assert query == "[image]"

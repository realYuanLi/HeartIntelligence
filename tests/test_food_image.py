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
            "portion_description": "6 oz",
            "portion_grams": 170,
            "calories": 280,
            "protein_g": 53.0,
            "carbs_g": 0.0,
            "fat_g": 6.1,
            "fiber_g": 0.0,
            "confidence": "high",
        },
        {
            "name": "Brown Rice",
            "portion_description": "1 cup",
            "portion_grams": 195,
            "calories": 216,
            "protein_g": 5.0,
            "carbs_g": 45.0,
            "fat_g": 1.8,
            "fiber_g": 3.5,
            "confidence": "medium",
        },
        {
            "name": "Steamed Broccoli",
            "portion_description": "1 cup",
            "portion_grams": 156,
            "calories": 55,
            "protein_g": 3.7,
            "carbs_g": 11.0,
            "fat_g": 0.6,
            "fiber_g": 5.1,
            "confidence": "high",
        },
    ],
})

# Mock USDA search results (per 100g values + portion data)
USDA_CHICKEN = {
    "food_description": "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
    "calories_per_100g": 165.0,
    "protein_per_100g": 31.0,
    "carbs_per_100g": 0.0,
    "fat_per_100g": 3.6,
    "fiber_per_100g": 0.0,
    "portions": [
        {"description": "1 unit (yield from 1 lb ready-to-cook chicken)", "gram_weight": 86.0},
        {"description": "0.5 breast, bone and skin removed", "gram_weight": 86.0},
    ],
    "source": "USDA FoodData Central",
}
USDA_RICE = {
    "food_description": "Rice, brown, long-grain, cooked",
    "calories_per_100g": 112.0,
    "protein_per_100g": 2.3,
    "carbs_per_100g": 23.5,
    "fat_per_100g": 0.8,
    "fiber_per_100g": 1.8,
    "portions": [
        {"description": "1 cup", "gram_weight": 195.0},
    ],
    "source": "USDA FoodData Central",
}
USDA_BROCCOLI = {
    "food_description": "Broccoli, cooked, boiled, drained, without salt",
    "calories_per_100g": 35.0,
    "protein_per_100g": 2.4,
    "carbs_per_100g": 7.2,
    "fat_per_100g": 0.4,
    "fiber_per_100g": 3.3,
    "portions": [
        {"description": "1 cup, chopped", "gram_weight": 156.0},
        {"description": "1 spear (about 5 inches long)", "gram_weight": 37.0},
    ],
    "source": "USDA FoodData Central",
}

def _mock_usda_search(food_name):
    """Return mock USDA data based on food name keyword matching."""
    name_lower = food_name.lower()
    if "chicken" in name_lower:
        return USDA_CHICKEN
    elif "rice" in name_lower:
        return USDA_RICE
    elif "broccoli" in name_lower:
        return USDA_BROCCOLI
    return None

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

    @patch("functions.food_image_analyzer._usda_search", side_effect=_mock_usda_search)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_food_detected_with_usda(self, mock_create, mock_usda):
        """Food detected: USDA cross-references should provide scaled nutrient values."""
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is True
        assert len(result["items"]) == 3
        assert result["items"][0]["name"] == "Grilled Chicken Breast"
        assert result["items"][0]["source"] == "USDA"
        assert result["items"][0]["usda_food"] is not None
        # Calorie range should be present (±20%)
        assert "calorie_range" in result["items"][0]
        assert len(result["items"][0]["calorie_range"]) == 2
        # Meal calorie range should be present
        assert "meal_calorie_range" in result
        assert result["profile_comparison"] is None  # no username
        assert isinstance(result["suggestions"], list)

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_food_detected_fallback_to_gpt(self, mock_create, mock_usda, mock_local):
        """When both USDA and local DB fail, GPT-4o estimates are used as fallback."""
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is True
        assert len(result["items"]) == 3
        # Falls back to GPT estimates from the vision response
        assert result["items"][0]["calories"] == 280  # from GPT response
        assert result["items"][0]["source"] == "estimate"
        assert "usda_food" not in result["items"][0]

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_non_food_image(self, mock_create, mock_usda):
        mock_create.return_value = _make_openai_response(NON_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["detected"] is False
        assert result["items"] == []

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_no_username_means_no_profile_comparison(self, mock_create, mock_usda):
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI, username="")

        assert result["detected"] is True
        assert result["profile_comparison"] is None

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.nutrition_plans._load_profile", return_value=SAMPLE_PROFILE)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_with_username_loads_profile(self, mock_create, mock_load, mock_usda):
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

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_json_with_code_fences(self, mock_create, mock_usda):
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
        with patch("functions.food_image_analyzer.openai.chat.completions.create") as mock_create, \
             patch("functions.food_image_analyzer._usda_search", return_value=None):
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

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_json_with_plain_code_fences(self, mock_create, mock_usda):
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

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_missing_fields_get_defaults(self, mock_create, mock_usda, mock_local):
        """An item with missing fields should get safe defaults (fallback path)."""
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
        # "medium" is downgraded to "low" on GPT fallback (no verified data)
        assert item["confidence"] == "low"
        assert item["source"] == "estimate"

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_completely_empty_item(self, mock_create, mock_usda, mock_local):
        """An empty dict item should still produce a sanitized entry."""
        mock_create.return_value = _make_openai_response(
            json.dumps({"detected": True, "items": [{}]})
        )
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert result["detected"] is True
        item = result["items"][0]
        assert item["name"] == "Unknown"

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_float_precision_is_rounded(self, mock_create, mock_usda, mock_local):
        """Nutrient floats should be rounded to 1 decimal place (fallback path)."""
        response = json.dumps({
            "detected": True,
            "items": [{
                "name": "Test",
                "portion_grams": 100,
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

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.nutrition_plans._load_profile", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_username_but_no_profile(self, mock_create, mock_load, mock_usda):
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


# ---------------------------------------------------------------------------
# Tests: USDA FoodData Central integration
# ---------------------------------------------------------------------------

class TestUsdaSearch:
    """Tests for the _usda_search helper."""

    @patch("functions.food_image_analyzer.requests.post")
    def test_successful_search(self, mock_post):
        """USDA search returns per-100g nutrient values for a matched food."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "foods": [{
                    "fdcId": 171077,
                    "description": "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
                    "foodNutrients": [
                        {"nutrientId": 1008, "value": 165.0},  # Energy kcal
                        {"nutrientId": 1003, "value": 31.0},   # Protein
                        {"nutrientId": 1004, "value": 3.6},    # Fat
                        {"nutrientId": 1005, "value": 0.0},    # Carbs
                        {"nutrientId": 1079, "value": 0.0},    # Fiber
                    ],
                }],
            },
        )
        result = fia._usda_search("chicken breast cooked")
        assert result is not None
        assert result["calories_per_100g"] == 165.0
        assert result["protein_per_100g"] == 31.0
        assert result["fat_per_100g"] == 3.6
        assert result["source"] == "USDA FoodData Central"

    @patch("functions.food_image_analyzer.requests.post")
    def test_no_results(self, mock_post):
        """USDA search with no matching foods returns None."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"foods": []},
        )
        result = fia._usda_search("xyzzy nonexistent food")
        assert result is None

    @patch("functions.food_image_analyzer.requests.post")
    def test_api_error_status(self, mock_post):
        """Non-200 status code returns None gracefully."""
        mock_post.return_value = MagicMock(status_code=429)
        result = fia._usda_search("banana")
        assert result is None

    @patch("functions.food_image_analyzer.requests.post")
    def test_network_error(self, mock_post):
        """Network error returns None, not an exception."""
        import requests as req
        mock_post.side_effect = req.ConnectionError("DNS resolution failed")
        result = fia._usda_search("banana")
        assert result is None

    @patch("functions.food_image_analyzer.requests.post")
    def test_missing_calorie_nutrient(self, mock_post):
        """If the calorie nutrient is missing, return None."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "foods": [{
                    "description": "Some food",
                    "foodNutrients": [
                        {"nutrientId": 1003, "value": 10.0},  # Protein only
                    ],
                }],
            },
        )
        result = fia._usda_search("some food")
        assert result is None


class TestScaleNutrients:
    """Tests for the _scale_nutrients helper."""

    def test_100g_no_scaling(self):
        usda = {
            "calories_per_100g": 200.0,
            "protein_per_100g": 25.0,
            "carbs_per_100g": 10.0,
            "fat_per_100g": 8.0,
            "fiber_per_100g": 3.0,
        }
        result = fia._scale_nutrients(usda, 100.0)
        assert result["calories"] == 200
        assert result["protein_g"] == 25.0
        assert result["fat_g"] == 8.0

    def test_150g_scaling(self):
        usda = {
            "calories_per_100g": 165.0,
            "protein_per_100g": 31.0,
            "carbs_per_100g": 0.0,
            "fat_per_100g": 3.6,
            "fiber_per_100g": 0.0,
        }
        result = fia._scale_nutrients(usda, 150.0)
        # 165 * 1.5 = 247.5 -> 248 (rounded)
        assert result["calories"] == 248
        assert result["protein_g"] == 46.5  # 31 * 1.5
        assert result["fat_g"] == 5.4       # 3.6 * 1.5

    def test_50g_scaling(self):
        usda = {
            "calories_per_100g": 300.0,
            "protein_per_100g": 20.0,
            "carbs_per_100g": 40.0,
            "fat_per_100g": 10.0,
            "fiber_per_100g": 5.0,
        }
        result = fia._scale_nutrients(usda, 50.0)
        assert result["calories"] == 150
        assert result["protein_g"] == 10.0
        assert result["carbs_g"] == 20.0


class TestUsdaCrossValidation:
    """Tests for the hybrid GPT-4o + USDA pipeline in analyze_food_image."""

    @patch("functions.food_image_analyzer._usda_search", side_effect=_mock_usda_search)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_usda_values_override_gpt_estimates(self, mock_create, mock_usda):
        """When USDA lookup succeeds, USDA values are used (not GPT estimates)."""
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        chicken = result["items"][0]
        assert chicken["source"] == "USDA"
        assert chicken["usda_food"] == USDA_CHICKEN["food_description"]
        # Calories come from USDA per-100g * portion_grams/100, not GPT's direct estimate
        # USDA: 165 kcal/100g, so any value is a scaled USDA value
        assert "calorie_range" in chicken
        assert len(chicken["calorie_range"]) == 2
        # Rice should use USDA portion: "1 cup" -> 195g from USDA portions
        rice = result["items"][1]
        assert rice["source"] == "USDA"
        # 112 kcal/100g * 195g/100 = 218.4 -> 218
        assert rice["calories"] == 218
        assert rice["weight_source"] == "usda_portion"

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search")
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_mixed_sources(self, mock_create, mock_usda, mock_local):
        """Some items from USDA, others from GPT fallback."""
        def partial_usda(name):
            if "chicken" in name.lower():
                return USDA_CHICKEN
            return None
        mock_usda.side_effect = partial_usda
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert result["items"][0]["source"] == "USDA"
        assert result["items"][1]["source"] == "estimate"
        assert result["items"][2]["source"] == "estimate"

    @patch("functions.food_image_analyzer._usda_search", side_effect=_mock_usda_search)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_usda_source_noted_in_format(self, mock_create, mock_usda):
        """Formatted output should show USDA source attribution."""
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        output = fia.format_food_image_analysis(result)

        assert "[USDA]" in output
        assert "USDA FoodData Central" in output

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_all_fallback_shows_estimate_tag(self, mock_create, mock_usda, mock_local):
        """When all lookups fail, items should show [est.] source."""
        mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        output = fia.format_food_image_analysis(result)

        assert "[est.]" in output
        assert "USDA FoodData Central" not in output


class TestFormatSourceTags:
    """Tests for source attribution in format_food_image_analysis."""

    def test_usda_item_shows_usda_tag(self):
        analysis = {
            "detected": True,
            "items": [{
                "name": "Banana",
                "estimated_portion": "1 medium",
                "calories": 105,
                "calorie_range": [84, 126],
                "protein_g": 1.3,
                "carbs_g": 27.0,
                "fat_g": 0.4,
                "fiber_g": 3.1,
                "confidence": "high",
                "source": "USDA",
                "usda_food": "Bananas, raw",
            }],
            "meal_total": {"calories": 105, "protein_g": 1.3, "carbs_g": 27.0, "fat_g": 0.4, "fiber_g": 3.1},
            "meal_calorie_range": [84, 126],
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[USDA]" in output
        assert "1/1 items verified" in output
        # Should show calorie range
        assert "84-126" in output

    def test_estimate_item_shows_est_tag(self):
        analysis = {
            "detected": True,
            "items": [{
                "name": "Dim Sum",
                "estimated_portion": "3 pieces",
                "calories": 180,
                "calorie_range": [144, 216],
                "protein_g": 8.0,
                "carbs_g": 20.0,
                "fat_g": 7.0,
                "fiber_g": 1.0,
                "confidence": "medium",
                "source": "estimate",
            }],
            "meal_total": {"calories": 180, "protein_g": 8.0, "carbs_g": 20.0, "fat_g": 7.0, "fiber_g": 1.0},
            "meal_calorie_range": [144, 216],
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[est.]" in output

    def test_local_db_item_shows_db_tag(self):
        analysis = {
            "detected": True,
            "items": [{
                "name": "Brown Rice",
                "estimated_portion": "1 cup",
                "calories": 216,
                "calorie_range": [173, 259],
                "protein_g": 5.0,
                "carbs_g": 45.0,
                "fat_g": 1.8,
                "fiber_g": 3.5,
                "confidence": "medium",
                "source": "local_db",
            }],
            "meal_total": {"calories": 216, "protein_g": 5.0, "carbs_g": 45.0, "fat_g": 1.8, "fiber_g": 3.5},
            "meal_calorie_range": [173, 259],
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "[DB]" in output
        # local_db counts as verified
        assert "1/1 items verified" in output


# ---------------------------------------------------------------------------
# Tests: _match_portion_to_grams
# ---------------------------------------------------------------------------

class TestMatchPortionToGrams:
    """Tests for USDA portion matching — the key accuracy improvement."""

    def test_exact_cup_match(self):
        """'1 cup' should match USDA portion '1 cup' with its gram weight."""
        portions = [{"description": "1 cup", "gram_weight": 195.0}]
        grams, source = fia._match_portion_to_grams("1 cup", portions, 200.0)
        assert grams == 195.0
        assert source == "usda_portion"

    def test_quantity_scaling(self):
        """'2 cups' should match '1 cup' portion and double the gram weight."""
        portions = [{"description": "1 cup", "gram_weight": 195.0}]
        grams, source = fia._match_portion_to_grams("2 cups", portions, 400.0)
        assert grams == 390.0
        assert source == "usda_portion"

    def test_no_match_falls_back_to_gpt(self):
        """When no USDA portion matches, fall back to GPT gram estimate."""
        portions = [{"description": "1 cup", "gram_weight": 195.0}]
        grams, source = fia._match_portion_to_grams("3 pieces", portions, 120.0)
        assert grams == 120.0
        assert source == "gpt_estimate"

    def test_empty_portions_list(self):
        """Empty USDA portions list should fall back to GPT estimate."""
        grams, source = fia._match_portion_to_grams("1 cup", [], 240.0)
        assert grams == 240.0
        assert source == "gpt_estimate"

    def test_best_match_among_multiple(self):
        """Should pick the best matching portion from multiple options."""
        portions = [
            {"description": "1 spear (about 5 inches long)", "gram_weight": 37.0},
            {"description": "1 cup, chopped", "gram_weight": 156.0},
        ]
        grams, source = fia._match_portion_to_grams("1 cup", portions, 160.0)
        assert grams == 156.0
        assert source == "usda_portion"

    def test_fractional_quantity(self):
        """'0.5 cup' should match and scale correctly."""
        portions = [{"description": "1 cup", "gram_weight": 195.0}]
        grams, source = fia._match_portion_to_grams("0.5 cup", portions, 100.0)
        assert grams == 97.5
        assert source == "usda_portion"


# ---------------------------------------------------------------------------
# Tests: _compute_calorie_range
# ---------------------------------------------------------------------------

class TestCalorieRange:
    """Tests for the confidence-based calorie range computation."""

    def test_high_confidence_narrow_range(self):
        """High confidence = ±15%."""
        low, high = fia._compute_calorie_range(500, "high")
        assert low == 425   # 500 * 0.85
        assert high == 575  # 500 * 1.15

    def test_medium_confidence_moderate_range(self):
        """Medium confidence = ±25%."""
        low, high = fia._compute_calorie_range(500, "medium")
        assert low == 375   # 500 * 0.75
        assert high == 625  # 500 * 1.25

    def test_low_confidence_wide_range(self):
        """Low confidence = ±40%."""
        low, high = fia._compute_calorie_range(500, "low")
        assert low == 300   # 500 * 0.6
        assert high == 700  # 500 * 1.4

    def test_zero_calories(self):
        low, high = fia._compute_calorie_range(0)
        assert low == 0
        assert high == 0

    def test_default_is_medium(self):
        """No confidence arg defaults to medium."""
        low, high = fia._compute_calorie_range(100)
        assert low == 75
        assert high == 125

    def test_range_in_meal_total(self):
        """Meal calorie range should appear in the analysis result."""
        analysis = {
            "detected": True,
            "items": [{
                "name": "Apple", "estimated_portion": "1 medium",
                "calories": 95, "calorie_range": [81, 109],
                "protein_g": 0.5, "carbs_g": 25.0, "fat_g": 0.3, "fiber_g": 4.4,
                "confidence": "high", "source": "USDA",
            }],
            "meal_total": {"calories": 95, "protein_g": 0.5, "carbs_g": 25.0, "fat_g": 0.3, "fiber_g": 4.4},
            "meal_calorie_range": [81, 109],
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "81-109" in output
        assert "likely" in output.lower()
        # Health disclaimer must always be present
        assert "not a substitute" in output.lower()


# ---------------------------------------------------------------------------
# Tests: _local_food_lookup
# ---------------------------------------------------------------------------

class TestLocalFoodLookup:
    """Tests for the local food database fallback."""

    def test_exact_match(self):
        """Exact name match should return the food entry."""
        # Reset cached DB so our mock is used
        fia._local_food_db = [
            {"name": "brown rice cooked", "serving": "1 cup", "calories": 216, "protein_g": 5.0,
             "carbs_g": 45.0, "fat_g": 1.8, "fiber_g": 3.5},
        ]
        result = fia._local_food_lookup("brown rice cooked")
        assert result is not None
        assert result["calories"] == 216
        fia._local_food_db = None  # reset

    def test_keyword_match(self):
        """Partial keyword overlap should still match."""
        fia._local_food_db = [
            {"name": "chicken breast", "serving": "4 oz", "calories": 187, "protein_g": 35.0,
             "carbs_g": 0.0, "fat_g": 4.0, "fiber_g": 0.0},
        ]
        result = fia._local_food_lookup("grilled chicken")
        assert result is not None
        assert result["name"] == "chicken breast"
        fia._local_food_db = None

    def test_no_match(self):
        """Completely unrelated food should return None."""
        fia._local_food_db = [
            {"name": "chicken breast", "serving": "4 oz", "calories": 187},
        ]
        result = fia._local_food_lookup("sushi roll")
        assert result is None
        fia._local_food_db = None

    def test_empty_db(self):
        fia._local_food_db = []
        result = fia._local_food_lookup("anything")
        assert result is None
        fia._local_food_db = None


# ---------------------------------------------------------------------------
# Tests: _usda_fetch_portions
# ---------------------------------------------------------------------------

class TestUsdaFetchPortions:
    """Tests for fetching USDA foodPortions."""

    @patch("functions.food_image_analyzer.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "foodPortions": [
                    {"amount": 1, "modifier": "cup", "gramWeight": 195.0, "portionDescription": ""},
                    {"amount": 1, "modifier": "oz", "gramWeight": 28.35, "portionDescription": ""},
                ],
            },
        )
        result = fia._usda_fetch_portions(171077)
        assert len(result) == 2
        assert result[0]["gram_weight"] == 195.0
        assert "cup" in result[0]["description"]

    @patch("functions.food_image_analyzer.requests.get")
    def test_api_failure(self, mock_get):
        mock_get.return_value = MagicMock(status_code=500)
        result = fia._usda_fetch_portions(171077)
        assert result == []

    @patch("functions.food_image_analyzer.requests.get")
    def test_zero_gram_weight_filtered(self, mock_get):
        """Portions with zero gram weight should be excluded."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "foodPortions": [
                    {"amount": 1, "modifier": "cup", "gramWeight": 0, "portionDescription": ""},
                    {"amount": 1, "modifier": "tbsp", "gramWeight": 15.0, "portionDescription": ""},
                ],
            },
        )
        result = fia._usda_fetch_portions(171077)
        assert len(result) == 1
        assert result[0]["gram_weight"] == 15.0


# ---------------------------------------------------------------------------
# Tests: Health disclaimer
# ---------------------------------------------------------------------------

class TestHealthDisclaimer:
    """Ensure disclaimer is always present in output."""

    def test_disclaimer_in_analysis_result(self):
        """analyze_food_image should include disclaimer in return dict."""
        with patch("functions.food_image_analyzer._usda_search", return_value=None), \
             patch("functions.food_image_analyzer._local_food_lookup", return_value=None), \
             patch("functions.food_image_analyzer.openai.chat.completions.create") as mock_create:
            mock_create.return_value = _make_openai_response(SAMPLE_FOOD_RESPONSE)
            result = fia.analyze_food_image(SAMPLE_DATA_URI)
        assert "disclaimer" in result
        assert "not a substitute" in result["disclaimer"].lower()

    def test_disclaimer_in_formatted_output(self):
        """Formatted output must always contain the health disclaimer."""
        analysis = {
            "detected": True,
            "items": [{
                "name": "Test", "estimated_portion": "1 cup",
                "calories": 100, "protein_g": 5.0, "carbs_g": 10.0,
                "fat_g": 3.0, "fiber_g": 1.0, "confidence": "high",
            }],
            "meal_total": {"calories": 100, "protein_g": 5.0, "carbs_g": 10.0, "fat_g": 3.0, "fiber_g": 1.0},
            "profile_comparison": None,
            "suggestions": [],
        }
        output = fia.format_food_image_analysis(analysis)
        assert "not a substitute" in output.lower()
        assert "registered dietitian" in output.lower()


# ---------------------------------------------------------------------------
# Tests: Cross-validation (USDA vs GPT)
# ---------------------------------------------------------------------------

class TestCrossValidation:
    """Tests for the USDA-vs-GPT cross-validation logic."""

    @patch("functions.food_image_analyzer._usda_search")
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_large_discrepancy_downgrades_confidence(self, mock_create, mock_usda):
        """When USDA and GPT calories differ >2x, confidence should be downgraded to low."""
        # GPT says 100 kcal, but USDA says 500 kcal (5x discrepancy)
        response = json.dumps({
            "detected": True,
            "items": [{
                "name": "mystery food",
                "portion_description": "1 cup",
                "portion_grams": 200,
                "calories": 100,  # GPT estimate
                "protein_g": 5.0, "carbs_g": 10.0, "fat_g": 3.0, "fiber_g": 1.0,
                "confidence": "high",
            }],
        })
        mock_create.return_value = _make_openai_response(response)
        mock_usda.return_value = {
            "food_description": "Mystery, cooked",
            "calories_per_100g": 250.0,  # 250 * 200/100 = 500 kcal (5x GPT's 100)
            "protein_per_100g": 10.0,
            "carbs_per_100g": 20.0,
            "fat_per_100g": 8.0,
            "fiber_per_100g": 2.0,
            "portions": [{"description": "1 cup", "gram_weight": 200.0}],
            "source": "USDA FoodData Central",
        }
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        # Confidence should be downgraded to "low" due to discrepancy
        assert result["items"][0]["confidence"] == "low"
        # Should still use USDA value (more reliable)
        assert result["items"][0]["calories"] == 500

    @patch("functions.food_image_analyzer._usda_search")
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_small_discrepancy_keeps_confidence(self, mock_create, mock_usda):
        """When USDA and GPT calories are close, confidence is preserved."""
        response = json.dumps({
            "detected": True,
            "items": [{
                "name": "banana raw",
                "portion_description": "1 medium",
                "portion_grams": 118,
                "calories": 105,  # GPT estimate
                "protein_g": 1.3, "carbs_g": 27.0, "fat_g": 0.4, "fiber_g": 3.1,
                "confidence": "high",
            }],
        })
        mock_create.return_value = _make_openai_response(response)
        mock_usda.return_value = {
            "food_description": "Bananas, raw",
            "calories_per_100g": 89.0,  # 89 * 118/100 = 105 kcal (matches GPT)
            "protein_per_100g": 1.1,
            "carbs_per_100g": 22.8,
            "fat_per_100g": 0.3,
            "fiber_per_100g": 2.6,
            "portions": [{"description": "1 medium (7 inches to 7-7/8 inches long)", "gram_weight": 118.0}],
            "source": "USDA FoodData Central",
        }
        result = fia.analyze_food_image(SAMPLE_DATA_URI)
        # Confidence should remain "high" since values agree
        assert result["items"][0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# Tests: Hidden calories
# ---------------------------------------------------------------------------

class TestHiddenCalories:
    """Tests for the hidden calories note from vision model."""

    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_hidden_calories_added_to_suggestions(self, mock_create, mock_local, mock_usda):
        """Vision model's hidden_calories_note should appear in suggestions."""
        response = json.dumps({
            "detected": True,
            "items": [{
                "name": "Caesar Salad",
                "portion_description": "1 bowl",
                "portion_grams": 300,
                "calories": 350,
                "protein_g": 15.0, "carbs_g": 20.0, "fat_g": 25.0, "fiber_g": 3.0,
                "confidence": "medium",
            }],
            "hidden_calories_note": "Visible Caesar dressing and parmesan cheese may add 150-200 kcal",
        })
        mock_create.return_value = _make_openai_response(response)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        assert any("Caesar dressing" in s for s in result["suggestions"])
        assert any("not be fully reflected" in s for s in result["suggestions"])


# ---------------------------------------------------------------------------
# Tests: GPT-fallback confidence downgrade
# ---------------------------------------------------------------------------

class TestFallbackConfidenceDowngrade:
    """When using GPT-only estimates, medium confidence is downgraded to low."""

    @patch("functions.food_image_analyzer._local_food_lookup", return_value=None)
    @patch("functions.food_image_analyzer._usda_search", return_value=None)
    @patch("functions.food_image_analyzer.openai.chat.completions.create")
    def test_medium_downgraded_to_low_on_gpt_fallback(self, mock_create, mock_usda, mock_local):
        """GPT-only items with 'medium' confidence get downgraded to 'low'."""
        response = json.dumps({
            "detected": True,
            "items": [{
                "name": "Exotic dish",
                "portion_description": "1 serving",
                "portion_grams": 200,
                "calories": 400,
                "protein_g": 20.0, "carbs_g": 40.0, "fat_g": 15.0, "fiber_g": 3.0,
                "confidence": "medium",
            }],
        })
        mock_create.return_value = _make_openai_response(response)
        result = fia.analyze_food_image(SAMPLE_DATA_URI)

        # Medium -> low when using GPT fallback (no verified data)
        assert result["items"][0]["confidence"] == "low"
        assert result["items"][0]["source"] == "estimate"
        # Range should be wide (±40% for low confidence)
        cal_range = result["items"][0]["calorie_range"]
        assert cal_range[0] == 240  # 400 * 0.6
        assert cal_range[1] == 560  # 400 * 1.4

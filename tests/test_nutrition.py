"""Comprehensive tests for the Personal Nutrition skill (nutrition_search + nutrition_plans)."""

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

# We need a minimal __init__.py so `functions` is a package for relative imports
_init_path = PROJECT_ROOT / "functions" / "__init__.py"
_created_init = False
if not _init_path.exists():
    _init_path.touch()
    _created_init = True

import functions.nutrition_search as ns
import functions.nutrition_plans as np_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_food_cache():
    """Reset the module-level lazy caches between tests."""
    ns._FOODS = None
    ns._RDA = None
    yield
    ns._FOODS = None
    ns._RDA = None


@pytest.fixture
def sample_profile_male():
    return {
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


@pytest.fixture
def sample_profile_female():
    return {
        "age": 25,
        "weight_kg": 60.0,
        "height_cm": 165.0,
        "sex": "female",
        "activity_level": "sedentary",
        "health_goals": ["weight_loss"],
        "allergies": [],
        "dietary_preferences": [],
        "lab_values": {},
    }


@pytest.fixture
def sample_plan():
    return {
        "plan_id": "abc12345",
        "title": "Test Balanced Plan",
        "active": True,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "duration_days": 7,
        "daily_targets": {
            "calories": 2200,
            "protein_g": 120,
            "carbs_g": 250,
            "fat_g": 70,
        },
        "days": {
            "monday": {
                "meals": [
                    {
                        "meal_type": "breakfast",
                        "name": "Oatmeal with Berries",
                        "ingredients": [
                            {"name": "oats rolled", "amount": "0.5 cup"},
                            {"name": "blueberries", "amount": "0.5 cup"},
                            {"name": "almond milk", "amount": "1 cup"},
                        ],
                        "calories": 350,
                        "protein_g": 10,
                        "carbs_g": 55,
                        "fat_g": 8,
                    },
                    {
                        "meal_type": "lunch",
                        "name": "Chicken Salad",
                        "ingredients": [
                            {"name": "chicken breast", "amount": "4 oz"},
                            {"name": "spinach raw", "amount": "2 cups"},
                            {"name": "olive oil", "amount": "1 tbsp"},
                        ],
                        "calories": 400,
                        "protein_g": 40,
                        "carbs_g": 5,
                        "fat_g": 18,
                    },
                ]
            }
        },
        "grocery_list": [
            {"name": "oats rolled", "amount": "2 cups", "category": "grains", "estimated_cost_usd": 2.50},
            {"name": "chicken breast", "amount": "2 lbs", "category": "protein", "estimated_cost_usd": 8.00},
            {"name": "blueberries", "amount": "2 cups", "category": "fruits", "estimated_cost_usd": 4.00},
            {"name": "spinach", "amount": "1 bag", "category": "vegetables", "estimated_cost_usd": 3.00},
            {"name": "olive oil", "amount": "1 bottle", "category": "fats_oils", "estimated_cost_usd": 6.00},
        ],
        "nutrient_alerts": [],
    }


@pytest.fixture
def flask_app():
    """Create a minimal Flask app with the nutrition blueprint registered."""
    from flask import Flask
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
    app.secret_key = "test-secret-key"
    app.config["TESTING"] = True
    app.register_blueprint(np_mod.nutrition_bp)
    return app


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide temporary directories for profile/plan persistence."""
    profiles = tmp_path / "profiles"
    plans = tmp_path / "plans"
    profiles.mkdir()
    plans.mkdir()
    return profiles, plans


# ============================================================================
# 1. UNIT TESTS — nutrition_search.py
# ============================================================================

class TestComputeDailyTargets:
    """Tests for compute_daily_targets()."""

    def test_male_30_moderate_maintenance(self, sample_profile_male):
        result = ns.compute_daily_targets(sample_profile_male)
        assert 1800 <= result["calories"] <= 2800, f"Unexpected calories: {result['calories']}"
        assert result["protein_g"] > 0
        assert result["carbs_g"] >= 50
        assert result["fat_g"] > 0
        assert "fiber_g" in result

    def test_female_25_sedentary_weight_loss(self, sample_profile_female):
        result = ns.compute_daily_targets(sample_profile_female)
        # Weight loss subtracts 500, sedentary is 1.2 multiplier, so should be lower
        assert result["calories"] >= 1200, "Should be clamped above 1200"
        assert result["calories"] <= 2000, "Sedentary + weight_loss should be under 2000"

    def test_weight_loss_lower_than_maintenance(self, sample_profile_male):
        maintenance = ns.compute_daily_targets(sample_profile_male)
        sample_profile_male["health_goals"] = ["weight_loss"]
        loss = ns.compute_daily_targets(sample_profile_male)
        assert loss["calories"] < maintenance["calories"]

    def test_muscle_gain_higher_than_maintenance(self, sample_profile_male):
        maintenance = ns.compute_daily_targets(sample_profile_male)
        sample_profile_male["health_goals"] = ["muscle_gain"]
        gain = ns.compute_daily_targets(sample_profile_male)
        assert gain["calories"] > maintenance["calories"]

    def test_goal_ordering(self, sample_profile_male):
        """weight_loss < maintenance < muscle_gain."""
        sample_profile_male["health_goals"] = ["weight_loss"]
        loss = ns.compute_daily_targets(sample_profile_male)["calories"]
        sample_profile_male["health_goals"] = []
        maint = ns.compute_daily_targets(sample_profile_male)["calories"]
        sample_profile_male["health_goals"] = ["muscle_gain"]
        gain = ns.compute_daily_targets(sample_profile_male)["calories"]
        assert loss < maint < gain

    def test_extreme_young_age(self):
        profile = {"age": 1, "weight_kg": 10, "height_cm": 60, "sex": "male"}
        result = ns.compute_daily_targets(profile)
        assert 1200 <= result["calories"] <= 4000

    def test_extreme_heavy_tall(self):
        profile = {"age": 40, "weight_kg": 300, "height_cm": 250, "sex": "male", "activity_level": "very_active"}
        result = ns.compute_daily_targets(profile)
        assert result["calories"] <= 4000, "Should be clamped to 4000"

    def test_extreme_light_short(self):
        profile = {"age": 90, "weight_kg": 30, "height_cm": 100, "sex": "female", "activity_level": "sedentary"}
        result = ns.compute_daily_targets(profile)
        assert result["calories"] >= 1200, "Should be clamped to 1200"

    def test_default_values_when_missing(self):
        """Empty profile should use defaults and not crash."""
        result = ns.compute_daily_targets({})
        assert 1200 <= result["calories"] <= 4000
        assert result["protein_g"] > 0

    def test_carbs_minimum_clamp(self):
        """Even with extreme macro splits, carbs should be >= 50."""
        profile = {"weight_kg": 200, "health_goals": ["muscle_gain"], "activity_level": "sedentary"}
        result = ns.compute_daily_targets(profile)
        assert result["carbs_g"] >= 50


class TestDetectNutrientGaps:
    """Tests for detect_nutrient_gaps()."""

    def test_low_vitamin_d(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {"vitamin_d_ng_ml": 18},
        }
        gaps = ns.detect_nutrient_gaps(profile)
        nutrient_names = [g["nutrient"] for g in gaps]
        assert "Vitamin D" in nutrient_names
        vd = next(g for g in gaps if g["nutrient"] == "Vitamin D")
        assert vd["status"] == "low"
        assert len(vd["food_suggestions"]) > 0

    def test_normal_vitamin_d(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {"vitamin_d_ng_ml": 40},
        }
        gaps = ns.detect_nutrient_gaps(profile)
        nutrient_names = [g["nutrient"] for g in gaps]
        assert "Vitamin D" not in nutrient_names

    def test_high_cholesterol(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {"cholesterol_total_mg_dl": 280},
        }
        gaps = ns.detect_nutrient_gaps(profile)
        nutrient_names = [g["nutrient"] for g in gaps]
        assert "Total Cholesterol" in nutrient_names
        chol = next(g for g in gaps if g["nutrient"] == "Total Cholesterol")
        assert chol["status"] == "high"

    def test_normal_cholesterol(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {"cholesterol_total_mg_dl": 180},
        }
        gaps = ns.detect_nutrient_gaps(profile)
        nutrient_names = [g["nutrient"] for g in gaps]
        assert "Total Cholesterol" not in nutrient_names

    def test_low_hdl(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {"hdl_mg_dl": 30},
        }
        gaps = ns.detect_nutrient_gaps(profile)
        assert any(g["nutrient"] == "HDL Cholesterol" and g["status"] == "low" for g in gaps)

    def test_high_hba1c(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {"hba1c_pct": 6.5},
        }
        gaps = ns.detect_nutrient_gaps(profile)
        assert any(g["nutrient"] == "HbA1c" and g["status"] == "high" for g in gaps)

    def test_all_null_lab_values(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {
                "vitamin_d_ng_ml": None,
                "iron_ug_dl": None,
                "cholesterol_total_mg_dl": None,
            },
        }
        gaps = ns.detect_nutrient_gaps(profile)
        # Should return a single "unknown" general message
        assert len(gaps) == 1
        assert gaps[0]["status"] == "unknown"

    def test_empty_lab_values(self):
        profile = {"age": 30, "sex": "male", "lab_values": {}}
        gaps = ns.detect_nutrient_gaps(profile)
        assert gaps == []

    def test_no_lab_values_key(self):
        profile = {"age": 30, "sex": "male"}
        gaps = ns.detect_nutrient_gaps(profile)
        assert gaps == []

    def test_multiple_gaps(self):
        profile = {
            "age": 30, "sex": "male",
            "lab_values": {
                "vitamin_d_ng_ml": 15,
                "cholesterol_total_mg_dl": 250,
                "iron_ug_dl": 40,
            },
        }
        gaps = ns.detect_nutrient_gaps(profile)
        nutrient_names = {g["nutrient"] for g in gaps}
        assert "Vitamin D" in nutrient_names
        assert "Total Cholesterol" in nutrient_names
        assert "Iron" in nutrient_names


class TestSearchFoods:
    """Tests for search_foods()."""

    def test_search_chicken(self):
        results = ns.search_foods("chicken")
        assert len(results) > 0
        names = [r["name"].lower() for r in results]
        assert any("chicken" in n for n in names)

    def test_search_high_protein(self):
        results = ns.search_foods("high protein")
        assert len(results) > 0
        # All results should have some protein
        for r in results:
            assert r.get("protein_g", 0) >= 0

    def test_search_high_protein_sorted(self):
        results = ns.search_foods("high protein")
        if len(results) >= 2:
            # Should be sorted descending by protein
            for i in range(len(results) - 1):
                assert results[i].get("protein_g", 0) >= results[i + 1].get("protein_g", 0)

    def test_empty_query(self):
        """Empty query should return empty (all tokens are stop words or nothing)."""
        results = ns.search_foods("")
        assert isinstance(results, list)
        # Empty string produces no tokens, so no results
        assert len(results) == 0

    def test_only_stop_words(self):
        results = ns.search_foods("show me some good food please")
        # All words are stop words, so clean_tokens is empty
        assert results == []

    def test_no_matches(self):
        results = ns.search_foods("xyznonexistentfood123")
        assert results == []

    def test_category_search_dairy(self):
        results = ns.search_foods("dairy")
        assert len(results) > 0
        categories = {r.get("category") for r in results}
        assert "dairy" in categories

    def test_category_search_vegetables(self):
        results = ns.search_foods("vegetables")
        assert len(results) > 0

    def test_max_results_limit(self):
        results = ns.search_foods("chicken", max_results=3)
        assert len(results) <= 3

    def test_low_fat_sorting(self):
        results = ns.search_foods("low fat")
        if len(results) >= 2:
            # "low" sets sort_high = False, so should be ascending
            for i in range(len(results) - 1):
                assert results[i].get("fat_g", 0) <= results[i + 1].get("fat_g", 0)

    def test_search_salmon(self):
        results = ns.search_foods("salmon")
        assert len(results) > 0
        assert any("salmon" in r["name"].lower() for r in results)


class TestFormatFoodResults:
    """Tests for format_food_results()."""

    def test_empty_list(self):
        result = ns.format_food_results([])
        assert result == ""

    def test_single_food(self):
        foods = [
            {
                "name": "chicken breast",
                "serving": "4 oz",
                "category": "protein",
                "calories": 187,
                "protein_g": 35.0,
                "carbs_g": 0.0,
                "fat_g": 4.0,
                "fiber_g": 0.0,
            }
        ]
        result = ns.format_food_results(foods)
        assert "Chicken Breast" in result
        assert "187" in result
        assert "35.0g" in result
        assert "### 1." in result
        assert "1 results" in result

    def test_multiple_foods(self):
        foods = [
            {"name": "chicken breast", "serving": "4 oz", "category": "protein",
             "calories": 187, "protein_g": 35, "carbs_g": 0, "fat_g": 4, "fiber_g": 0},
            {"name": "salmon fillet", "serving": "4 oz", "category": "protein",
             "calories": 233, "protein_g": 25, "carbs_g": 0, "fat_g": 14, "fiber_g": 0},
        ]
        result = ns.format_food_results(foods)
        assert "### 1." in result
        assert "### 2." in result
        assert "2 results" in result

    def test_markdown_structure(self):
        foods = [{"name": "banana", "serving": "1 medium", "category": "fruits",
                   "calories": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.4, "fiber_g": 3.1}]
        result = ns.format_food_results(foods)
        assert "**" in result  # Bold formatting
        assert "###" in result  # Heading
        assert "---" not in result  # Only 1 item, no separator


class TestHelperFunctions:
    """Tests for internal helpers: _normalize, _stem, _tokenize, _get_rda_key."""

    def test_normalize(self):
        assert ns._normalize("  Hello   World  ") == "hello world"
        assert ns._normalize(None) == ""
        assert ns._normalize("") == ""

    def test_stem_plural(self):
        assert ns._stem("apples") == "apple"
        assert ns._stem("eggs") == "egg"

    def test_stem_no_strip_short(self):
        assert ns._stem("as") == "as"  # Too short
        assert ns._stem("bus") == "bus"  # Ends with s but len <= 3

    def test_stem_double_s(self):
        assert ns._stem("grass") == "grass"  # Ends with "ss"

    def test_tokenize(self):
        tokens = ns._tokenize("Chicken Breasts")
        assert "chicken" in tokens
        assert "breast" in tokens  # Stemmed from "breasts"

    def test_get_rda_key_young_male(self):
        assert ns._get_rda_key({"age": 25, "sex": "male"}) == "19-30_male"

    def test_get_rda_key_middle_female(self):
        assert ns._get_rda_key({"age": 45, "sex": "female"}) == "31-50_female"

    def test_get_rda_key_senior(self):
        assert ns._get_rda_key({"age": 65, "sex": "male"}) == "51-70_male"

    def test_get_rda_key_elderly(self):
        assert ns._get_rda_key({"age": 80, "sex": "female"}) == "71+_female"

    def test_get_rda_key_defaults(self):
        assert ns._get_rda_key({}) == "19-30_male"


# ============================================================================
# 2. UNIT TESTS — nutrition_plans.py
# ============================================================================

class TestValidateProfileFields:
    """Tests for _validate_profile_fields()."""

    def test_valid_input(self):
        data = {"age": 30, "weight_kg": 75, "height_cm": 178, "sex": "male", "activity_level": "moderate"}
        result = np_mod._validate_profile_fields(data)
        assert result["age"] == 30
        assert result["weight_kg"] == 75.0
        assert result["height_cm"] == 178.0
        assert result["sex"] == "male"
        assert result["activity_level"] == "moderate"

    def test_string_age_defaults(self):
        result = np_mod._validate_profile_fields({"age": "abc"})
        assert result["age"] == 30

    def test_age_zero_clamped(self):
        result = np_mod._validate_profile_fields({"age": 0})
        assert result["age"] == 1

    def test_age_200_clamped(self):
        result = np_mod._validate_profile_fields({"age": 200})
        assert result["age"] == 120

    def test_negative_age(self):
        result = np_mod._validate_profile_fields({"age": -5})
        assert result["age"] == 1

    def test_invalid_sex_defaults(self):
        result = np_mod._validate_profile_fields({"sex": "helicopter"})
        assert result["sex"] == "male"

    def test_sex_case_insensitive(self):
        result = np_mod._validate_profile_fields({"sex": "Female"})
        assert result["sex"] == "female"

    def test_non_list_allergies(self):
        result = np_mod._validate_profile_fields({"allergies": "peanuts"})
        assert result["allergies"] == []

    def test_list_allergies(self):
        result = np_mod._validate_profile_fields({"allergies": ["peanuts", "shellfish"]})
        assert result["allergies"] == ["peanuts", "shellfish"]

    def test_invalid_activity_level(self):
        result = np_mod._validate_profile_fields({"activity_level": "extreme"})
        assert result["activity_level"] == "moderate"

    def test_weight_clamped_low(self):
        result = np_mod._validate_profile_fields({"weight_kg": 5})
        assert result["weight_kg"] == 20.0

    def test_weight_clamped_high(self):
        result = np_mod._validate_profile_fields({"weight_kg": 500})
        assert result["weight_kg"] == 300.0

    def test_height_clamped(self):
        result = np_mod._validate_profile_fields({"height_cm": 10})
        assert result["height_cm"] == 50.0
        result2 = np_mod._validate_profile_fields({"height_cm": 300})
        assert result2["height_cm"] == 250.0

    def test_invalid_weight_string(self):
        result = np_mod._validate_profile_fields({"weight_kg": "heavy"})
        assert result["weight_kg"] == 70.0

    def test_lab_values_valid(self):
        result = np_mod._validate_profile_fields({"lab_values": {"vitamin_d_ng_ml": 25.0, "iron_ug_dl": None}})
        assert result["lab_values"]["vitamin_d_ng_ml"] == 25.0
        assert result["lab_values"]["iron_ug_dl"] is None

    def test_lab_values_invalid_string(self):
        result = np_mod._validate_profile_fields({"lab_values": {"vitamin_d_ng_ml": "high"}})
        assert result["lab_values"]["vitamin_d_ng_ml"] is None

    def test_lab_values_not_dict(self):
        result = np_mod._validate_profile_fields({"lab_values": "not a dict"})
        assert "lab_values" not in result

    def test_budget_valid(self):
        result = np_mod._validate_profile_fields({"weekly_budget_usd": 150})
        assert result["weekly_budget_usd"] == 150.0

    def test_budget_none(self):
        result = np_mod._validate_profile_fields({"weekly_budget_usd": None})
        assert result["weekly_budget_usd"] is None

    def test_budget_invalid(self):
        result = np_mod._validate_profile_fields({"weekly_budget_usd": "cheap"})
        assert result["weekly_budget_usd"] is None

    def test_empty_data(self):
        result = np_mod._validate_profile_fields({})
        assert result == {}

    def test_unknown_keys_ignored(self):
        result = np_mod._validate_profile_fields({"unknown_field": 42, "age": 25})
        assert "unknown_field" not in result
        assert result["age"] == 25

    def test_dietary_preferences_non_list(self):
        result = np_mod._validate_profile_fields({"dietary_preferences": "vegan"})
        assert result["dietary_preferences"] == []

    def test_health_goals_non_list(self):
        result = np_mod._validate_profile_fields({"health_goals": "lose weight"})
        assert result["health_goals"] == []


class TestValidateAllergens:
    """Tests for _validate_allergens()."""

    def test_no_allergens_in_profile(self):
        plan_data = {"days": {"monday": {"meals": [
            {"name": "Oatmeal", "ingredients": [{"name": "oats"}]}
        ]}}}
        result = np_mod._validate_allergens(plan_data, [])
        assert result == []

    def test_allergen_found(self):
        plan_data = {"days": {"monday": {"meals": [
            {"name": "PB Sandwich", "ingredients": [
                {"name": "peanut butter"},
                {"name": "whole wheat bread"},
            ]}
        ]}}}
        result = np_mod._validate_allergens(plan_data, ["peanut"])
        assert len(result) == 1
        assert result[0]["allergen"] == "peanut"
        assert result[0]["day"] == "monday"
        assert result[0]["meal"] == "PB Sandwich"

    def test_case_insensitive_matching(self):
        plan_data = {"days": {"tuesday": {"meals": [
            {"name": "Shrimp Pasta", "ingredients": [{"name": "Shrimp"}]}
        ]}}}
        result = np_mod._validate_allergens(plan_data, ["SHRIMP"])
        assert len(result) == 1

    def test_no_allergen_match(self):
        plan_data = {"days": {"monday": {"meals": [
            {"name": "Chicken Salad", "ingredients": [
                {"name": "chicken breast"},
                {"name": "lettuce"},
            ]}
        ]}}}
        result = np_mod._validate_allergens(plan_data, ["peanut", "shellfish"])
        assert result == []

    def test_multiple_allergens_multiple_days(self):
        plan_data = {"days": {
            "monday": {"meals": [
                {"name": "Breakfast", "ingredients": [{"name": "milk"}, {"name": "eggs"}]},
            ]},
            "tuesday": {"meals": [
                {"name": "Lunch", "ingredients": [{"name": "peanut butter"}]},
            ]},
        }}
        result = np_mod._validate_allergens(plan_data, ["milk", "peanut"])
        assert len(result) == 2

    def test_empty_plan_days(self):
        result = np_mod._validate_allergens({"days": {}}, ["peanut"])
        assert result == []

    def test_no_days_key(self):
        result = np_mod._validate_allergens({}, ["peanut"])
        assert result == []

    def test_non_dict_day_data(self):
        """Graceful handling of malformed day data."""
        plan_data = {"days": {"monday": "not a dict"}}
        result = np_mod._validate_allergens(plan_data, ["peanut"])
        assert result == []


class TestProfileCRUD:
    """Tests for profile save/load with temp directories."""

    def test_save_and_load_profile(self, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            profile = {"age": 25, "sex": "female", "weight_kg": 60.0}
            np_mod._save_profile("testuser", profile)
            loaded = np_mod._load_profile("testuser")
            assert loaded is not None
            assert loaded["age"] == 25
            assert loaded["sex"] == "female"
            assert "updated_at" in loaded

    def test_load_nonexistent_profile(self, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            assert np_mod._load_profile("nobody") is None

    def test_save_and_load_pantry(self, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            pantry = {"items": [{"name": "rice"}, {"name": "beans"}], "updated_at": None}
            np_mod._save_pantry("testuser", pantry)
            loaded = np_mod._load_pantry("testuser")
            assert len(loaded["items"]) == 2
            assert loaded["items"][0]["name"] == "rice"

    def test_load_nonexistent_pantry(self, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            pantry = np_mod._load_pantry("nobody")
            assert pantry == {"items": [], "updated_at": None}


class TestPlanCRUD:
    """Tests for plan save/load/active management."""

    def test_save_and_load_plans(self, tmp_data_dir, sample_plan):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            np_mod._save_plans("testuser", [sample_plan])
            loaded = np_mod._load_plans("testuser")
            assert len(loaded) == 1
            assert loaded[0]["plan_id"] == "abc12345"

    def test_get_active_plan(self, tmp_data_dir, sample_plan):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            np_mod._save_plans("testuser", [sample_plan])
            active = np_mod._get_active_plan("testuser")
            assert active is not None
            assert active["active"] is True

    def test_no_active_plan(self, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            assert np_mod._get_active_plan("testuser") is None

    def test_set_active_plan_deactivates_previous(self, tmp_data_dir, sample_plan):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            np_mod._set_active_plan("testuser", sample_plan)
            new_plan = dict(sample_plan)
            new_plan["plan_id"] = "new12345"
            new_plan["title"] = "New Plan"
            np_mod._set_active_plan("testuser", new_plan)
            plans = np_mod._load_plans("testuser")
            active_plans = [p for p in plans if p.get("active")]
            assert len(active_plans) == 1
            assert active_plans[0]["plan_id"] == "new12345"

    def test_load_plans_nonexistent(self, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            assert np_mod._load_plans("nobody") == []


class TestGetGrocerySummary:
    """Tests for get_grocery_summary()."""

    def test_plan_with_grocery_list(self, sample_plan):
        result = np_mod.get_grocery_summary(sample_plan)
        assert "Grocery List" in result
        assert "Oats Rolled" in result
        assert "Chicken Breast" in result
        assert "$" in result

    def test_plan_without_grocery_list(self, sample_plan):
        sample_plan["grocery_list"] = []
        result = np_mod.get_grocery_summary(sample_plan)
        assert "No grocery list" in result

    def test_no_plan(self):
        result = np_mod.get_grocery_summary(None)
        assert "No active nutrition plan" in result

    def test_total_cost_calculation(self, sample_plan):
        result = np_mod.get_grocery_summary(sample_plan)
        # Total = 2.50 + 8.00 + 4.00 + 3.00 + 6.00 = 23.50
        assert "$23.50" in result

    def test_items_without_cost(self):
        plan = {
            "title": "Test",
            "grocery_list": [
                {"name": "salt", "amount": "1 tsp", "category": "condiments", "estimated_cost_usd": None},
            ],
        }
        result = np_mod.get_grocery_summary(plan)
        assert "Salt" in result
        # No total since the only item has no cost
        assert "Estimated total" not in result


class TestGetPlanSummary:
    """Tests for get_plan_summary()."""

    def test_none_plan(self):
        result = np_mod.get_plan_summary(None)
        assert "No active nutrition plan" in result

    def test_empty_plan(self):
        # Note: {} is falsy in Python, so get_plan_summary treats it as "no plan"
        result = np_mod.get_plan_summary({})
        assert "No active nutrition plan" in result

    def test_plan_with_alerts(self, sample_plan):
        sample_plan["nutrient_alerts"] = [
            {"nutrient": "Vitamin D", "status": "low", "message": "Your Vitamin D is low."},
        ]
        result = np_mod.get_plan_summary(sample_plan)
        assert "Nutrient Alerts" in result
        assert "Vitamin D" in result

    def test_plan_summary_includes_meals(self, sample_plan):
        result = np_mod.get_plan_summary(sample_plan)
        assert "Monday" in result
        assert "Oatmeal with Berries" in result


# ============================================================================
# 3. EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:
    """Edge cases and adversarial inputs."""

    def test_empty_profile_all_defaults(self):
        """Completely empty profile should produce valid targets."""
        targets = ns.compute_daily_targets({})
        assert all(k in targets for k in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g"))

    def test_profile_with_every_field(self):
        profile = {
            "age": 35, "weight_kg": 80.0, "height_cm": 180.0, "sex": "male",
            "activity_level": "active",
            "health_goals": ["muscle_gain"],
            "allergies": ["peanuts", "shellfish", "dairy", "gluten", "soy"],
            "dietary_preferences": ["keto"],
            "lab_values": {
                "vitamin_d_ng_ml": 20,
                "iron_ug_dl": 50,
                "cholesterol_total_mg_dl": 210,
                "ldl_mg_dl": 110,
                "hdl_mg_dl": 55,
                "b12_pg_ml": 300,
                "hba1c_pct": 5.0,
            },
        }
        targets = ns.compute_daily_targets(profile)
        assert 1200 <= targets["calories"] <= 4000
        gaps = ns.detect_nutrient_gaps(profile)
        # Should detect vitamin D low (20 < 30) and cholesterol high (210 > 200)
        # and LDL high (110 > 100)
        names = [g["nutrient"] for g in gaps]
        assert "Vitamin D" in names
        assert "Total Cholesterol" in names
        assert "LDL Cholesterol" in names

    def test_plan_with_zero_meals(self):
        plan = {
            "title": "Empty Plan",
            "daily_targets": {},
            "days": {"monday": {"meals": []}},
            "grocery_list": [],
            "nutrient_alerts": [],
        }
        summary = np_mod.get_plan_summary(plan)
        assert "Empty Plan" in summary

    def test_very_long_allergy_list(self):
        allergies = [f"allergen_{i}" for i in range(100)]
        plan_data = {"days": {"monday": {"meals": [
            {"name": "Meal", "ingredients": [{"name": "allergen_50 soup"}]}
        ]}}}
        warnings = np_mod._validate_allergens(plan_data, allergies)
        # "allergen_5" is a substring of "allergen_50", so both match via `in` check
        assert len(warnings) >= 1
        matched_allergens = {w["allergen"] for w in warnings}
        assert "allergen_50" in matched_allergens
        # Verify substring matching behavior: "allergen_5" also matches "allergen_50 soup"
        assert "allergen_5" in matched_allergens

    def test_validate_profile_fields_all_bad_inputs(self):
        data = {
            "age": "old",
            "weight_kg": "heavy",
            "height_cm": "tall",
            "sex": 999,
            "activity_level": None,
            "allergies": 42,
            "dietary_preferences": True,
            "health_goals": {"not": "a list"},
            "weekly_budget_usd": "free",
            "lab_values": "bad",
        }
        result = np_mod._validate_profile_fields(data)
        assert result["age"] == 30
        assert result["weight_kg"] == 70.0
        assert result["height_cm"] == 170.0
        assert result["sex"] == "male"
        assert result["activity_level"] == "moderate"
        assert result["allergies"] == []
        assert result["dietary_preferences"] == []
        assert result["health_goals"] == []
        assert result["weekly_budget_usd"] is None
        assert "lab_values" not in result  # Non-dict lab_values is skipped


# ============================================================================
# 4. INTEGRATION-STYLE TESTS (Flask routes, no LLM calls)
# ============================================================================

class TestFlaskRoutes:
    """Test Flask Blueprint routes using the test client."""

    def test_blueprint_registered(self, flask_app):
        rules = [rule.rule for rule in flask_app.url_map.iter_rules()]
        assert "/api/nutrition-profile" in rules
        assert "/api/nutrition-pantry" in rules
        assert "/api/nutrition-plan" in rules
        assert "/api/nutrition-plan/grocery-list" in rules
        assert "/api/nutrition-plan/nutrient-gaps" in rules

    def test_get_profile_requires_login(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/nutrition-profile")
            assert resp.status_code == 401

    def test_post_profile_requires_login(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/nutrition-profile",
                data=json.dumps({"age": 25}),
                content_type="application/json",
            )
            assert resp.status_code == 401

    def test_get_profile_logged_in(self, flask_app, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                resp = client.get("/api/nutrition-profile")
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["success"] is True
                assert data["profile"] is None  # No profile yet

    def test_post_and_get_profile(self, flask_app, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                # Save profile
                resp = client.post(
                    "/api/nutrition-profile",
                    data=json.dumps({"age": 28, "sex": "female", "weight_kg": 65}),
                    content_type="application/json",
                )
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["success"] is True
                assert data["profile"]["age"] == 28

                # Load profile
                resp = client.get("/api/nutrition-profile")
                data = resp.get_json()
                assert data["profile"]["age"] == 28
                assert data["profile"]["sex"] == "female"

    def test_get_pantry_requires_login(self, flask_app):
        with flask_app.test_client() as client:
            resp = client.get("/api/nutrition-pantry")
            assert resp.status_code == 401

    def test_pantry_crud(self, flask_app, tmp_data_dir):
        profiles_dir, _ = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                # Save pantry
                resp = client.post(
                    "/api/nutrition-pantry",
                    data=json.dumps({"items": [{"name": "rice"}, {"name": "beans"}]}),
                    content_type="application/json",
                )
                assert resp.status_code == 200
                # Load pantry
                resp = client.get("/api/nutrition-pantry")
                data = resp.get_json()
                assert len(data["pantry"]["items"]) == 2

    def test_get_plan_no_plan(self, flask_app, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                resp = client.get("/api/nutrition-plan")
                data = resp.get_json()
                assert data["success"] is True
                assert data["plan"] is None

    def test_grocery_list_no_plan(self, flask_app, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                resp = client.get("/api/nutrition-plan/grocery-list")
                assert resp.status_code == 404

    def test_nutrient_gaps_no_profile(self, flask_app, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                resp = client.get("/api/nutrition-plan/nutrient-gaps")
                assert resp.status_code == 400

    def test_create_plan_no_profile(self, flask_app, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["username"] = "testuser"
                resp = client.post(
                    "/api/nutrition-plan",
                    data=json.dumps({"details": "Make me a plan"}),
                    content_type="application/json",
                )
                assert resp.status_code == 400


class TestHandleNutritionTool:
    """Tests for handle_nutrition_tool() dispatch function."""

    def test_no_username(self):
        result = np_mod.handle_nutrition_tool("view_plan", "", "")
        assert "Error" in result

    def test_unknown_action(self, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("dance", "", "testuser")
            assert "Unknown action" in result

    def test_view_plan_no_plan(self, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("view_plan", "", "testuser")
            assert "No active nutrition plan" in result

    def test_modify_plan_no_plan(self, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("modify_plan", "less carbs", "testuser")
            assert "No active nutrition plan" in result

    def test_grocery_list_no_plan(self, tmp_data_dir):
        _, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("grocery_list", "", "testuser")
            assert "No active nutrition plan" in result or "Create one first" in result

    def test_create_plan_no_profile(self, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("create_plan", "balanced plan", "testuser")
            assert "profile" in result.lower()

    def test_nutrient_check_no_profile(self, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("nutrient_check", "", "testuser")
            assert "profile" in result.lower()

    def test_update_profile(self, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            details = json.dumps({"age": 28, "sex": "female"})
            result = np_mod.handle_nutrition_tool("update_profile", details, "testuser")
            assert "updated" in result.lower()
            # Verify it was saved
            loaded = np_mod._load_profile("testuser")
            assert loaded["age"] == 28

    def test_update_profile_invalid_json(self, tmp_data_dir):
        profiles_dir, plans_dir = tmp_data_dir
        with patch.object(np_mod, "PROFILES_DIR", profiles_dir), \
             patch.object(np_mod, "PLANS_DIR", plans_dir):
            result = np_mod.handle_nutrition_tool("update_profile", "not json", "testuser")
            # Should not crash; uses empty updates
            assert "updated" in result.lower()


# ============================================================================
# Cleanup
# ============================================================================

def teardown_module():
    """Remove temporary __init__.py if we created it."""
    global _created_init
    if _created_init and _init_path.exists():
        _init_path.unlink()

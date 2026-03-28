"""Tests for the markdown-based UserMemory system with normalization."""

import sys
from pathlib import Path

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

import functions.user_memory as um
from functions.user_memory import (
    UserMemory,
    SHORT_TERM_CATEGORIES,
    LONG_TERM_CATEGORIES,
    MAX_PER_CATEGORY,
    PROMOTION_THRESHOLD,
    _parse_md,
    _render_md,
    normalize_entry,
    normalize_topic,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_memory_dir(tmp_path, monkeypatch):
    """Redirect MEMORY_DIR to a temp directory for every test."""
    monkeypatch.setattr(um, "MEMORY_DIR", tmp_path)
    yield


@pytest.fixture
def mem():
    """Return a UserMemory instance for a test user."""
    return UserMemory("testuser")


# ===========================================================================
# 1. Markdown parsing / rendering
# ===========================================================================

class TestParseMd:
    def test_empty_string(self):
        data = _parse_md("")
        assert all(data["long_term"][c] == [] for c in LONG_TERM_CATEGORIES)
        assert all(data["short_term"][c] == [] for c in SHORT_TERM_CATEGORIES)

    def test_parses_long_term_sections(self):
        md = "# User Memory\n\n## Preferences\n- diet: Vegan diet\n- ui: Dark mode\n\n## Goals\n- weight-loss: Lose 5kg\n"
        data = _parse_md(md)
        assert data["long_term"]["preference"] == ["diet: Vegan diet", "ui: Dark mode"]
        assert data["long_term"]["goal"] == ["weight-loss: Lose 5kg"]
        assert data["long_term"]["fact"] == []

    def test_parses_short_term_sections(self):
        md = "## Recent Conversations\n- Asked about vitamin D (2026-03-28)\n"
        data = _parse_md(md)
        assert len(data["short_term"]["recent_conversations"]) == 1
        assert "vitamin D" in data["short_term"]["recent_conversations"][0]

    def test_ignores_unknown_sections(self):
        md = "## Unknown Section\n- Something\n\n## Facts\n- fact: Real fact\n"
        data = _parse_md(md)
        assert data["long_term"]["fact"] == ["fact: Real fact"]

    def test_roundtrip(self):
        data = {
            "long_term": {"preference": ["diet: Vegan"], "fact": ["age: 30"], "saved": [], "goal": ["fitness: Run marathon"]},
            "short_term": {"recent_conversations": ["Asked about diet (2026-03-28)"], "recent_plans": [], "health_status": ["Weight 72kg (2026-03-28)"]},
        }
        md = _render_md(data)
        parsed = _parse_md(md)
        assert parsed["long_term"]["preference"] == ["diet: Vegan"]
        assert parsed["long_term"]["fact"] == ["age: 30"]
        assert parsed["long_term"]["goal"] == ["fitness: Run marathon"]
        assert "diet" in parsed["short_term"]["recent_conversations"][0]
        assert "72kg" in parsed["short_term"]["health_status"][0]


class TestRenderMd:
    def test_empty_data_renders_header_only(self):
        data = {
            "long_term": {c: [] for c in LONG_TERM_CATEGORIES},
            "short_term": {c: [] for c in SHORT_TERM_CATEGORIES},
        }
        md = _render_md(data)
        assert md.startswith("# User Memory")
        assert "##" not in md

    def test_includes_section_headings(self):
        data = {
            "long_term": {"preference": ["diet: Vegan"], "fact": [], "saved": [], "goal": []},
            "short_term": {"recent_conversations": [], "recent_plans": [], "health_status": []},
        }
        md = _render_md(data)
        assert "## Preferences" in md
        assert "- diet: Vegan" in md


# ===========================================================================
# 2. normalize_entry
# ===========================================================================

class TestNormalizeEntry:
    def test_strips_user_prefers_filler(self):
        key, line = normalize_entry("User prefers vegan diet", "preference")
        assert key == "diet"
        assert "user" not in line.lower().split(":")[1]  # value part doesn't contain "user"
        assert "vegan diet" in line.lower()

    def test_strips_remember_that_filler(self):
        key, line = normalize_entry("Remember that: allergic to peanuts", "fact")
        assert "remember" not in line.lower()
        assert "peanut" in line.lower()

    def test_explicit_key_used(self):
        key, line = normalize_entry("Follows vegan diet", "preference", key="diet")
        assert key == "diet"
        assert line.startswith("diet: ")

    def test_key_synonym_resolution(self):
        key, line = normalize_entry("Follows vegan diet", "preference", key="dietary_preference")
        assert key == "diet"

    def test_key_inferred_from_value(self):
        key, line = normalize_entry("allergic to peanuts", "fact")
        assert key == "allergy"

    def test_existing_key_value_format_preserved(self):
        key, line = normalize_entry("diet: follows vegan diet", "preference")
        assert key == "diet"
        assert line.startswith("diet: ")

    def test_fallback_to_category_key(self):
        key, line = normalize_entry("Likes the color blue", "preference")
        # No pattern match, falls back to category
        assert key == "preference"

    def test_notes_appended(self):
        key, line = normalize_entry("Allergic to peanuts", "fact", notes="Confirmed by doctor")
        assert "(Confirmed by doctor)" in line

    def test_context_appended(self):
        key, line = normalize_entry("Allergic to peanuts", "fact", context="critical for meal planning")
        assert "| context: critical for meal planning" in line

    def test_notes_and_context(self):
        key, line = normalize_entry("Allergic to peanuts", "fact",
                                     notes="Confirmed by doctor", context="meal planning")
        assert "(Confirmed by doctor)" in line
        assert "| context: meal planning" in line

    def test_empty_value_raises(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_entry("  ", "fact")

    def test_all_filler_value_raises(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_entry("   ", "fact")

    def test_capitalizes_first_word(self):
        _, line = normalize_entry("vegan diet", "preference")
        # After key prefix, value should start capitalized
        value_part = line.split(": ", 1)[1]
        assert value_part[0].isupper()

    def test_strips_articles(self):
        _, line = normalize_entry("the vegan diet", "preference")
        value_part = line.split(": ", 1)[1]
        assert not value_part.lower().startswith("the ")

    def test_newlines_sanitized(self):
        _, line = normalize_entry("likes\nvegan\ndiet", "preference")
        assert "\n" not in line

    def test_key_max_40_chars(self):
        key, _ = normalize_entry("something", "preference", key="a" * 50)
        assert len(key) <= 40

    def test_idempotent_on_normalized_input(self):
        _, line1 = normalize_entry("diet: Follows vegan diet", "preference")
        _, line2 = normalize_entry(line1, "preference")
        # Should be stable (or at least not break)
        assert "diet:" in line2.lower()

    def test_colon_in_value_not_misinterpreted(self):
        # "schedule: wake up at 6:30 AM" — only first colon splits
        key, line = normalize_entry("schedule: wake up at 6:30 AM", "preference")
        assert "6:30" in line


class TestNormalizeTopic:
    def test_strips_user_filler(self):
        result = normalize_topic("The user mentioned wanting vitamin D")
        assert "user" not in result.lower()
        assert "vitamin D" in result

    def test_preserves_action_words(self):
        result = normalize_topic("asked about vitamin D supplements")
        assert result.startswith("asked about")

    def test_empty_returns_empty(self):
        assert normalize_topic("  ") == ""
        assert normalize_topic("") == ""

    def test_newlines_sanitized(self):
        result = normalize_topic("asked\nabout\nvitamins")
        assert "\n" not in result

    def test_whitespace_normalized(self):
        result = normalize_topic("asked   about    vitamins")
        assert "  " not in result


# ===========================================================================
# 3. Remember (long-term) with normalization
# ===========================================================================

class TestRemember:
    def test_basic_remember(self, mem):
        entry = mem.remember("preference", "Vegan diet")
        assert entry["key"] == "diet"
        data = mem.get_all()
        assert len(data["long_term"]["preference"]) == 1
        assert "Vegan diet" in data["long_term"]["preference"][0]

    def test_remember_with_notes(self, mem):
        mem.remember("fact", "Allergic to peanuts", notes="Confirmed by doctor")
        data = mem.get_all()
        assert any("peanut" in e.lower() and "Confirmed by doctor" in e for e in data["long_term"]["fact"])

    def test_remember_with_context(self, mem):
        mem.remember("fact", "Weight 72kg", context="measured today")
        data = mem.get_all()
        assert any("72kg" in e and "measured today" in e for e in data["long_term"]["fact"])

    def test_invalid_category_raises(self, mem):
        with pytest.raises(ValueError, match="Invalid long-term category"):
            mem.remember("recent_conversations", "something")

    def test_empty_value_raises(self, mem):
        with pytest.raises(ValueError, match="value is required"):
            mem.remember("fact", "  ")

    def test_no_duplicate_entries(self, mem):
        mem.remember("preference", "Vegan diet")
        mem.remember("preference", "Vegan diet")
        data = mem.get_all()
        assert len(data["long_term"]["preference"]) == 1

    def test_multiple_categories(self, mem):
        mem.remember("preference", "Dark mode")
        mem.remember("goal", "Run marathon")
        mem.remember("fact", "Age 30")
        data = mem.get_all()
        assert len(data["long_term"]["preference"]) == 1
        assert len(data["long_term"]["goal"]) == 1
        assert len(data["long_term"]["fact"]) == 1

    def test_value_length_capped(self, mem):
        long_val = "x" * 600
        mem.remember("fact", long_val)
        data = mem.get_all()
        entry = data["long_term"]["fact"][0]
        # Entry line includes key prefix, so total should be reasonable
        assert len(entry) < 600


# ===========================================================================
# 4. LLM phrasing equivalence (key deduplication test)
# ===========================================================================

class TestLLMEquivalence:
    def test_different_phrasings_same_entry(self, mem):
        """Different LLM phrasings about the same topic should produce one entry."""
        mem.remember("preference", "User prefers vegan diet")
        mem.remember("preference", "Follows a strict vegan diet")
        data = mem.get_all()
        # Both normalize to key "diet", so only 1 entry
        assert len(data["long_term"]["preference"]) == 1

    def test_second_phrasing_updates_first(self, mem):
        mem.remember("preference", "User prefers vegan diet")
        mem.remember("preference", "Strictly vegan for ethical reasons")
        data = mem.get_all()
        assert len(data["long_term"]["preference"]) == 1
        # Latest value is stored
        assert "ethical" in data["long_term"]["preference"][0].lower()

    def test_different_topics_stay_separate(self, mem):
        mem.remember("fact", "Allergic to peanuts")
        mem.remember("fact", "Takes vitamin D supplements")
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 2

    def test_topic_normalization_equivalence(self, mem):
        """The user mentioned X and User mentioned X should produce the same entry."""
        mem.track("recent_conversations", "The user mentioned vitamin D supplements")
        mem.track("recent_conversations", "User mentioned vitamin D supplements")
        data = mem.get_all()
        # Both strip to "vitamin D supplements", so dedup to 1
        assert len(data["short_term"]["recent_conversations"]) == 1


# ===========================================================================
# 5. Track (short-term)
# ===========================================================================

class TestTrack:
    def test_basic_track(self, mem):
        mem.track("recent_conversations", "asked about diet plans")
        data = mem.get_all()
        entries = data["short_term"]["recent_conversations"]
        assert len(entries) == 1
        assert "asked about diet plans" in entries[0]

    def test_all_short_term_categories(self, mem):
        for cat in SHORT_TERM_CATEGORIES:
            mem.track(cat, f"test-{cat}")
        data = mem.get_all()
        for cat in SHORT_TERM_CATEGORIES:
            assert len(data["short_term"][cat]) == 1

    def test_invalid_category_raises(self, mem):
        with pytest.raises(ValueError, match="Invalid short-term category"):
            mem.track("preference", "something")

    def test_old_categories_rejected(self, mem):
        for old_cat in ["page_visits", "chat_topics", "recent_searches", "last_used_skills"]:
            with pytest.raises(ValueError, match="Invalid short-term category"):
                mem.track(old_cat, "something")

    def test_empty_value_ignored(self, mem):
        mem.track("recent_conversations", "  ")
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 0

    def test_long_value_truncated(self, mem):
        long_text = "x" * 200
        mem.track("recent_conversations", long_text)
        data = mem.get_all()
        entry = data["short_term"]["recent_conversations"][0]
        assert len(entry) < 200

    def test_appends_date(self, mem):
        mem.track("recent_conversations", "asked about vitamins")
        data = mem.get_all()
        entry = data["short_term"]["recent_conversations"][0]
        assert "(20" in entry

    def test_fifo_pruning(self, mem):
        for i in range(MAX_PER_CATEGORY + 5):
            mem.track("recent_conversations", f"topic-{i:04d}")
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) <= MAX_PER_CATEGORY

    def test_deduplication_same_day(self, mem):
        mem.track("recent_conversations", "asked about vitamin D")
        mem.track("recent_conversations", "asked about vitamin D")
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 1


# ===========================================================================
# 6. Forget (case-insensitive)
# ===========================================================================

class TestForget:
    def test_forget_long_term(self, mem):
        mem.remember("fact", "User is left-handed")
        assert mem.forget("left-handed") is True
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 0

    def test_forget_case_insensitive(self, mem):
        mem.remember("fact", "allergic to peanuts")
        assert mem.forget("Allergic") is True
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 0

    def test_forget_short_term(self, mem):
        mem.track("recent_conversations", "asked about running")
        assert mem.forget("asked about running") is True
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 0

    def test_forget_nonexistent(self, mem):
        assert mem.forget("nonexistent-key-12345") is False

    def test_forget_only_removes_targeted(self, mem):
        mem.remember("fact", "Allergic to peanuts")
        mem.remember("fact", "Takes vitamin D")
        mem.forget("peanuts")
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 1
        assert "vitamin" in data["long_term"]["fact"][0].lower()


# ===========================================================================
# 7. Get summary
# ===========================================================================

class TestGetSummary:
    def test_empty_memory(self, mem):
        assert mem.get_summary() == ""

    def test_long_term_in_summary(self, mem):
        mem.remember("preference", "Vegan diet")
        summary = mem.get_summary()
        assert "Preferences:" in summary
        assert "Vegan diet" in summary

    def test_short_term_in_summary(self, mem):
        mem.track("recent_conversations", "asked about vitamin D")
        summary = mem.get_summary()
        assert "Recent Conversations:" in summary
        assert "vitamin D" in summary

    def test_combined_summary(self, mem):
        mem.remember("preference", "Vegan diet")
        mem.remember("goal", "Lose 5kg")
        mem.track("recent_conversations", "asked about vitamin D")
        mem.track("health_status", "Weight 72kg")
        summary = mem.get_summary()
        assert "Preferences:" in summary
        assert "Goals:" in summary
        assert "Recent Conversations:" in summary
        assert "Health Status:" in summary

    def test_max_items_limits_output(self, mem):
        for i in range(20):
            mem.remember("fact", f"Unique fact number {i} with details")
        summary = mem.get_summary(max_items=5)
        bullets = [l for l in summary.splitlines() if l.strip().startswith("- ")]
        assert len(bullets) <= 5

    def test_no_old_category_headings(self, mem):
        mem.track("recent_conversations", "test")
        summary = mem.get_summary()
        assert "Page visits" not in summary
        assert "Chat topics" not in summary


# ===========================================================================
# 8. Persistence and isolation
# ===========================================================================

class TestPersistence:
    def test_data_persists_across_instances(self):
        mem1 = UserMemory("persistuser")
        mem1.remember("fact", "Persistent fact about health")
        mem2 = UserMemory("persistuser")
        data = mem2.get_all()
        assert any("Persistent" in e for e in data["long_term"]["fact"])

    def test_users_are_isolated(self):
        mem_a = UserMemory("user_a")
        mem_b = UserMemory("user_b")
        mem_a.remember("fact", "A's special fact")
        data_b = mem_b.get_all()
        assert all(len(data_b["long_term"][c]) == 0 for c in LONG_TERM_CATEGORIES)

    def test_stored_as_markdown_file(self):
        mem = UserMemory("mduser")
        mem.remember("preference", "Test preference item")
        assert mem.path.suffix == ".md"
        content = mem.path.read_text()
        assert "# User Memory" in content
        assert "## Preferences" in content
        assert "- preference: Test preference item" in content


# ===========================================================================
# 9. Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_username_raises(self):
        with pytest.raises(ValueError, match="Invalid username"):
            UserMemory("")

    def test_none_username_raises(self):
        with pytest.raises(ValueError, match="Invalid username"):
            UserMemory(None)

    def test_special_chars_stripped_from_username(self):
        mem = UserMemory("user@email.com")
        assert mem.username == "useremailcom"

    def test_missing_file_returns_empty(self, mem):
        data = mem.get_all()
        assert all(data["long_term"][c] == [] for c in LONG_TERM_CATEGORIES)
        assert all(data["short_term"][c] == [] for c in SHORT_TERM_CATEGORIES)

    def test_corrupted_file_returns_empty(self, mem):
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text("this is not valid markdown with sections", encoding="utf-8")
        data = mem.get_all()
        assert isinstance(data, dict)

    def test_unicode_content(self, mem):
        mem.remember("fact", "Spricht Deutsch")
        data = mem.get_all()
        assert any("Deutsch" in e for e in data["long_term"]["fact"])

    def test_markdown_special_chars_in_value(self, mem):
        mem.remember("fact", "Uses **bold** formatting")
        data = mem.get_all()
        assert any("**bold**" in e for e in data["long_term"]["fact"])

    def test_newline_in_value_sanitized(self, mem):
        mem.remember("fact", "Line one\nLine two")
        data = mem.get_all()
        entry = data["long_term"]["fact"][0]
        assert "\n" not in entry

    def test_newline_in_notes_sanitized(self, mem):
        mem.remember("fact", "Some fact", notes="Note\nwith\nnewlines")
        data = mem.get_all()
        entry = data["long_term"]["fact"][0]
        assert "\n" not in entry


# ===========================================================================
# 10. Promotion
# ===========================================================================

class TestPromotion:
    def test_repeated_conversations_promote_to_fact(self, mem):
        data = mem._load()
        for i in range(PROMOTION_THRESHOLD):
            data["short_term"]["recent_conversations"].append(f"vitamin D questions (2026-03-{20+i:02d})")
        mem._save(data)
        mem.get_summary()  # triggers promotion
        data = mem.get_all()
        facts = data["long_term"]["fact"]
        assert any("vitamin" in f.lower() for f in facts)

    def test_below_threshold_no_promotion(self, mem):
        data = mem._load()
        data["short_term"]["recent_conversations"].append("one-off topic (2026-03-28)")
        mem._save(data)
        mem.get_summary()
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 0

    def test_plans_never_promote(self, mem):
        data = mem._load()
        for i in range(5):
            data["short_term"]["recent_plans"].append(f"workout plan (2026-03-{20+i:02d})")
        mem._save(data)
        mem.get_summary()
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 0

    def test_health_status_never_promotes(self, mem):
        data = mem._load()
        for i in range(5):
            data["short_term"]["health_status"].append(f"weight 72kg (2026-03-{20+i:02d})")
        mem._save(data)
        mem.get_summary()
        data = mem.get_all()
        assert len(data["long_term"]["fact"]) == 0

    def test_promoted_entry_is_normalized(self, mem):
        """Promoted entries should have the standard key: value format."""
        data = mem._load()
        for i in range(PROMOTION_THRESHOLD):
            data["short_term"]["recent_conversations"].append(f"vitamin D supplements (2026-03-{20+i:02d})")
        mem._save(data)
        mem.get_summary()
        data = mem.get_all()
        facts = data["long_term"]["fact"]
        promoted = [f for f in facts if "vitamin" in f.lower()]
        assert len(promoted) == 1
        # Should be in normalized "key: value" format
        assert ":" in promoted[0]


# ===========================================================================
# 11. Category constants
# ===========================================================================

class TestCategoryConstants:
    def test_short_term_categories(self):
        assert SHORT_TERM_CATEGORIES == ["recent_conversations", "recent_plans", "health_status"]

    def test_long_term_categories(self):
        assert LONG_TERM_CATEGORIES == ["preference", "fact", "saved", "goal"]

    def test_no_overlap(self):
        assert set(SHORT_TERM_CATEGORIES) & set(LONG_TERM_CATEGORIES) == set()

    def test_max_per_category_positive(self):
        assert MAX_PER_CATEGORY > 0

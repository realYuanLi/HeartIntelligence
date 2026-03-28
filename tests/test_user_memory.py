"""Comprehensive tests for the UserMemory system (user_memory.py)."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

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
    DEFAULT_SHORT_TERM_TTL,
    _OLD_SHORT_TERM_CATEGORIES,
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
# 1. Unit tests for UserMemory class
# ===========================================================================

class TestRemember:
    def test_creates_long_term_entry_with_correct_fields(self, mem):
        entry = mem.remember("preference", "Dark mode enabled", key="ui-theme")
        assert entry["key"] == "ui-theme"
        assert entry["category"] == "preference"
        assert entry["value"] == "Dark mode enabled"
        assert entry["notes"] is None
        assert entry["ttl"] is None
        assert "ts" in entry
        assert isinstance(entry["ts"], float)

    def test_upserts_existing_entry(self, mem):
        mem.remember("preference", "Light mode", key="ui-theme")
        entry = mem.remember("preference", "Dark mode", key="ui-theme")
        data = mem.get_all()
        # Should be only one entry with that key
        matches = [e for e in data["long_term"] if e["key"] == "ui-theme"]
        assert len(matches) == 1
        assert matches[0]["value"] == "Dark mode"

    def test_stores_notes_field(self, mem):
        entry = mem.remember("fact", "Allergic to peanuts", key="allergy-1",
                             notes="Confirmed by doctor 2024-01")
        assert entry["notes"] == "Confirmed by doctor 2024-01"

    def test_invalid_category_raises_value_error(self, mem):
        with pytest.raises(ValueError, match="Invalid long-term category"):
            mem.remember("recent_conversations", "something")

    def test_auto_generates_key_if_none(self, mem):
        entry = mem.remember("goal", "Run a marathon")
        assert entry["key"].startswith("goal-")
        assert len(entry["key"]) > len("goal-")

    def test_remember_with_ttl(self, mem):
        entry = mem.remember("saved", "Temporary bookmark", ttl=3600)
        assert entry["ttl"] == 3600


class TestTrack:
    def test_creates_short_term_entry(self, mem):
        entry = mem.track("recent_conversations", "asked about diet plans")
        assert entry["value"] == "asked about diet plans"
        assert "key" in entry
        assert "ts" in entry
        assert entry["ttl"] == DEFAULT_SHORT_TERM_TTL

    def test_custom_ttl(self, mem):
        entry = mem.track("recent_conversations", "weather", ttl=120)
        assert entry["ttl"] == 120

    def test_stored_in_correct_category(self, mem):
        mem.track("recent_plans", "5-day strength routine")
        data = mem.get_all()
        assert len(data["short_term"]["recent_plans"]) == 1
        assert data["short_term"]["recent_plans"][0]["value"] == "5-day strength routine"

    def test_invalid_category_raises_value_error(self, mem):
        with pytest.raises(ValueError, match="Invalid short-term category"):
            mem.track("preference", "something")

    def test_old_categories_rejected(self, mem):
        for old_cat in _OLD_SHORT_TERM_CATEGORIES:
            with pytest.raises(ValueError, match="Invalid short-term category"):
                mem.track(old_cat, "something")

    def test_all_valid_short_term_categories(self, mem):
        for cat in SHORT_TERM_CATEGORIES:
            entry = mem.track(cat, f"test-{cat}")
            assert entry["value"] == f"test-{cat}"


class TestForget:
    def test_removes_long_term_entry(self, mem):
        entry = mem.remember("fact", "User is left-handed", key="hand")
        assert mem.forget("hand") is True
        data = mem.get_all()
        assert len(data["long_term"]) == 0

    def test_removes_short_term_entry(self, mem):
        entry = mem.track("recent_conversations", "asked about running")
        key = entry["key"]
        assert mem.forget(key) is True
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 0

    def test_returns_false_for_nonexistent_key(self, mem):
        assert mem.forget("nonexistent-key-12345") is False

    def test_forget_only_removes_targeted_entry(self, mem):
        mem.remember("fact", "Fact A", key="a")
        mem.remember("fact", "Fact B", key="b")
        mem.forget("a")
        data = mem.get_all()
        assert len(data["long_term"]) == 1
        assert data["long_term"][0]["key"] == "b"


class TestGetAll:
    def test_returns_full_structure(self, mem):
        data = mem.get_all()
        assert "short_term" in data
        assert "long_term" in data
        assert isinstance(data["long_term"], list)
        for cat in SHORT_TERM_CATEGORIES:
            assert cat in data["short_term"]
            assert isinstance(data["short_term"][cat], list)

    def test_includes_all_entries(self, mem):
        mem.remember("preference", "dark mode", key="theme")
        mem.track("recent_conversations", "asked about exercise")
        data = mem.get_all()
        assert len(data["long_term"]) == 1
        assert len(data["short_term"]["recent_conversations"]) == 1


class TestGetSummary:
    def test_returns_empty_string_when_no_memories(self, mem):
        assert mem.get_summary() == ""

    def test_includes_long_term_memories(self, mem):
        mem.remember("preference", "Vegan diet", key="diet")
        summary = mem.get_summary()
        assert "Long-term memories:" in summary
        assert "Vegan diet" in summary
        assert "[preference]" in summary

    def test_includes_notes_in_summary(self, mem):
        mem.remember("fact", "Allergic to shellfish", key="allergy",
                     notes="EpiPen prescribed")
        summary = mem.get_summary()
        assert "EpiPen prescribed" in summary

    def test_includes_recent_conversations(self, mem):
        mem.track("recent_conversations", "asked about machine learning")
        summary = mem.get_summary()
        assert "Recent conversations:" in summary
        assert "asked about machine learning" in summary

    def test_includes_active_plans(self, mem):
        mem.track("recent_plans", "5-day strength program")
        summary = mem.get_summary()
        assert "Active plans:" in summary
        assert "5-day strength program" in summary

    def test_includes_health_status(self, mem):
        mem.track("health_status", "BMI 24.5, blood pressure 120/80")
        summary = mem.get_summary()
        assert "Recent health status:" in summary
        assert "BMI 24.5" in summary

    def test_max_items_limits_output(self, mem):
        for i in range(15):
            mem.remember("fact", f"Fact number {i}", key=f"fact-{i}")
        summary = mem.get_summary(max_items=5)
        assert "... and 10 more" in summary

    def test_summary_combines_short_term_sections(self, mem):
        mem.track("recent_conversations", "topic1")
        mem.track("recent_plans", "plan1")
        summary = mem.get_summary()
        assert "topic1" in summary
        assert "plan1" in summary


# ===========================================================================
# 2. TTL expiry tests
# ===========================================================================

class TestTTLExpiry:
    def test_expired_short_term_entry_removed(self, mem):
        """Entry with ttl=1 should be cleaned up after expiry."""
        entry = mem.track("recent_conversations", "old topic", ttl=1)
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 1

        real_time = time.time
        with patch("functions.user_memory.time") as mock_time:
            mock_time.time.return_value = real_time() + 2
            data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 0

    def test_none_ttl_never_expires(self, mem):
        """Long-term entry with ttl=None should persist forever."""
        mem.remember("fact", "Permanent fact", key="perm", ttl=None)
        real_time = time.time
        with patch("functions.user_memory.time") as mock_time:
            mock_time.time.return_value = real_time() + 365 * 24 * 3600  # 1 year later
            data = mem.get_all()
        assert len(data["long_term"]) == 1

    def test_ttl_zero_expires_immediately(self, mem):
        """Entry with ttl=0 should expire on next load."""
        mem.track("recent_conversations", "ephemeral", ttl=0)
        real_time = time.time
        with patch("functions.user_memory.time") as mock_time:
            mock_time.time.return_value = real_time() + 0.001
            data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 0

    def test_expired_long_term_entry_removed(self, mem):
        """Long-term entry with TTL should also expire."""
        mem.remember("saved", "Temp bookmark", key="bm1", ttl=5)
        real_time = time.time
        with patch("functions.user_memory.time") as mock_time:
            mock_time.time.return_value = real_time() + 10
            data = mem.get_all()
        assert len(data["long_term"]) == 0


# ===========================================================================
# 3. FIFO pruning tests
# ===========================================================================

class TestFIFOPruning:
    def test_prunes_to_max_per_category(self, mem):
        """Adding more than MAX_PER_CATEGORY entries keeps only the newest."""
        for i in range(25):
            mem.track("recent_conversations", f"topic-{i}")
        data = mem.get_all()
        entries = data["short_term"]["recent_conversations"]
        assert len(entries) == MAX_PER_CATEGORY  # 20

    def test_oldest_entries_dropped(self, mem):
        """The 5 oldest entries (0-4) should be dropped when 25 are added."""
        for i in range(25):
            mem.track("recent_conversations", f"topic-{i}")
        data = mem.get_all()
        values = [e["value"] for e in data["short_term"]["recent_conversations"]]
        for i in range(5):
            assert f"topic-{i}" not in values
        for i in range(5, 25):
            assert f"topic-{i}" in values

    def test_fifo_preserves_order(self, mem):
        """Entries should be in insertion order after pruning."""
        for i in range(25):
            mem.track("recent_conversations", f"topic-{i}")
        data = mem.get_all()
        values = [e["value"] for e in data["short_term"]["recent_conversations"]]
        expected = [f"topic-{i}" for i in range(5, 25)]
        assert values == expected


# ===========================================================================
# 4. Persistence tests
# ===========================================================================

class TestPersistence:
    def test_data_persists_across_instances(self, tmp_path):
        """New UserMemory instance for same user sees previous data."""
        mem1 = UserMemory("alice")
        mem1.remember("preference", "Likes cats", key="pet-pref")
        mem1.track("recent_conversations", "feline health")

        mem2 = UserMemory("alice")
        data = mem2.get_all()
        assert len(data["long_term"]) == 1
        assert data["long_term"][0]["value"] == "Likes cats"
        assert len(data["short_term"]["recent_conversations"]) == 1

    def test_no_cross_user_leakage(self, tmp_path):
        """Different usernames must get independent files."""
        mem_a = UserMemory("userA")
        mem_b = UserMemory("userB")
        mem_a.remember("fact", "Secret A", key="secret")
        mem_b.remember("fact", "Secret B", key="secret")

        data_a = mem_a.get_all()
        data_b = mem_b.get_all()
        assert data_a["long_term"][0]["value"] == "Secret A"
        assert data_b["long_term"][0]["value"] == "Secret B"

    def test_file_path_uses_username(self, tmp_path):
        mem = UserMemory("janedoe")
        mem.remember("fact", "something", key="x")
        assert (tmp_path / "janedoe.json").exists()


# ===========================================================================
# 5. Edge case tests
# ===========================================================================

class TestEdgeCases:
    def test_empty_username_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid username"):
            UserMemory("")

    def test_none_username_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid username"):
            UserMemory(None)

    def test_special_characters_sanitized(self):
        mem = UserMemory("user@name!#$%")
        assert mem.username == "username"

    def test_username_with_spaces_sanitized(self):
        mem = UserMemory("john doe")
        assert mem.username == "johndoe"

    def test_username_only_special_chars_raises(self):
        with pytest.raises(ValueError, match="Invalid username"):
            UserMemory("@#$%^&*()")

    def test_corrupted_json_file_recovers(self, tmp_path):
        """If the JSON file is corrupted, UserMemory should recover gracefully."""
        mem = UserMemory("corrupt")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text("{{not valid json!!!", encoding="utf-8")
        data = mem.get_all()
        assert "short_term" in data
        assert "long_term" in data
        assert isinstance(data["long_term"], list)

    def test_missing_file_returns_default(self, tmp_path):
        mem = UserMemory("newuser")
        data = mem.get_all()
        assert data["long_term"] == []
        for cat in SHORT_TERM_CATEGORIES:
            assert data["short_term"][cat] == []

    def test_malformed_structure_heals(self, tmp_path):
        """If the file has wrong structure, it should be healed on load."""
        mem = UserMemory("malformed")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text(json.dumps({"short_term": "not a dict", "long_term": "not a list"}),
                            encoding="utf-8")
        data = mem.get_all()
        assert isinstance(data["short_term"], dict)
        assert isinstance(data["long_term"], list)

    def test_partial_structure_heals(self, tmp_path):
        """If short_term is missing some categories, they get re-added."""
        mem = UserMemory("partial")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text(json.dumps({
            "short_term": {"recent_conversations": []},
            "long_term": [],
        }), encoding="utf-8")
        data = mem.get_all()
        for cat in SHORT_TERM_CATEGORIES:
            assert cat in data["short_term"]


# ===========================================================================
# 6. API tests (Flask test client)
# ===========================================================================

class TestAPI:
    """Test the Flask Blueprint endpoints using a test client."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        """Create a minimal Flask app with the memory blueprint."""
        from flask import Flask
        from flask_login import LoginManager
        from functions.user_memory import memory_bp

        app = Flask(__name__)
        app.secret_key = "test-secret"
        lm = LoginManager()
        lm.init_app(app)
        lm.user_loader(lambda uid: None)
        app.register_blueprint(memory_bp)
        app.config["TESTING"] = True
        return app.test_client()

    @staticmethod
    def _login(client, username="apiuser"):
        """Helper to set session username."""
        with client.session_transaction() as sess:
            sess["username"] = username

    def test_get_memory_requires_auth(self, client):
        resp = client.get("/api/memory")
        assert resp.status_code == 401

    def test_get_memory_returns_structure(self, client):
        self._login(client)
        resp = client.get("/api/memory")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "memory" in body

    def test_remember_creates_entry(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "preference",
            "value": "Dark mode",
            "key": "theme",
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["entry"]["value"] == "Dark mode"

    def test_remember_requires_value(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "preference",
            "value": "",
        })
        assert resp.status_code == 400

    def test_remember_rejects_invalid_category(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "invalid_cat",
            "value": "something",
        })
        assert resp.status_code == 400

    def test_remember_rejects_long_value(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "x" * 501,
        })
        assert resp.status_code == 400

    def test_remember_rejects_negative_ttl(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
            "ttl": -10,
        })
        assert resp.status_code == 400

    def test_forget_removes_entry(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "To be deleted",
            "key": "del-me",
        })
        assert resp.status_code == 200
        resp = client.delete("/api/memory/del-me")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_forget_nonexistent_returns_404(self, client):
        self._login(client)
        resp = client.delete("/api/memory/no-such-key")
        assert resp.status_code == 404

    def test_track_creates_entry(self, client):
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "asked about diet",
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["entry"]["value"] == "asked about diet"

    def test_track_rejects_invalid_category(self, client):
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "preference",
            "value": "something",
        })
        assert resp.status_code == 400

    def test_track_rejects_old_categories(self, client):
        self._login(client)
        for old_cat in _OLD_SHORT_TERM_CATEGORIES:
            resp = client.post("/api/memory/track", json={
                "category": old_cat,
                "value": "something",
            })
            assert resp.status_code == 400

    def test_track_rejects_long_value(self, client):
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "x" * 201,
        })
        assert resp.status_code == 400

    def test_track_requires_auth(self, client):
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "something",
        })
        assert resp.status_code == 401

    def test_remember_rejects_long_key(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
            "key": "k" * 201,
        })
        assert resp.status_code == 400

    def test_remember_rejects_long_notes(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
            "notes": "n" * 501,
        })
        assert resp.status_code == 400


# ===========================================================================
# 7. New-feature tests: context, evergreen, relevance, promotion, API fields
# ===========================================================================

from functions.user_memory import _relevance_score, _backfill_entry, PROMOTION_THRESHOLD


class TestContextAndEvergreen:
    def test_remember_stores_context(self, mem):
        entry = mem.remember("preference", "No sugar", key="sugar", context="for meals")
        assert entry["context"] == "for meals"

    def test_remember_stores_evergreen(self, mem):
        entry = mem.remember("fact", "Birthday is Jan 1", key="bday", evergreen=True)
        assert entry["evergreen"] is True

    def test_remember_defaults_no_context_no_evergreen(self, mem):
        entry = mem.remember("fact", "Some fact", key="def")
        assert entry["context"] is None
        assert entry["evergreen"] is False
        assert entry["access_count"] == 0

    def test_upsert_preserves_access_count(self, mem):
        mem.remember("fact", "Original", key="ac-test")
        data = mem.get_all()
        for e in data["long_term"]:
            if e["key"] == "ac-test":
                e["access_count"] = 7
        mem._save(data)
        entry = mem.remember("fact", "Updated", key="ac-test")
        assert entry["access_count"] == 7
        assert entry["value"] == "Updated"


class TestBackfillDefaults:
    def test_legacy_file_gets_defaults(self, tmp_path):
        """Old-format entries without context/evergreen/access_count get defaults on load."""
        mem = UserMemory("legacy")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        legacy_data = {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": [
                {"key": "old1", "category": "fact", "value": "Old fact", "notes": None, "ts": time.time(), "ttl": None}
            ],
        }
        mem.path.write_text(json.dumps(legacy_data), encoding="utf-8")
        data = mem.get_all()
        entry = data["long_term"][0]
        assert entry["context"] is None
        assert entry["evergreen"] is False
        assert entry["access_count"] == 0

    def test_backfill_does_not_overwrite_existing(self, tmp_path):
        """If context is already set, backfill must not overwrite it."""
        mem = UserMemory("existing")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        data_with_context = {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": [
                {"key": "e1", "category": "fact", "value": "Fact", "notes": None,
                 "context": "meal planning", "evergreen": True, "access_count": 5,
                 "ts": time.time(), "ttl": None}
            ],
        }
        mem.path.write_text(json.dumps(data_with_context), encoding="utf-8")
        data = mem.get_all()
        entry = data["long_term"][0]
        assert entry["context"] == "meal planning"
        assert entry["evergreen"] is True
        assert entry["access_count"] == 5


class TestRelevanceScoring:
    def test_newer_entries_score_higher(self):
        now = time.time()
        new_entry = {"ts": now, "access_count": 0, "evergreen": False}
        old_entry = {"ts": now - 60 * 86400, "access_count": 0, "evergreen": False}
        assert _relevance_score(new_entry, now) > _relevance_score(old_entry, now)

    def test_evergreen_entries_get_max_decay(self):
        now = time.time()
        old_evergreen = {"ts": now - 365 * 86400, "access_count": 0, "evergreen": True}
        score = _relevance_score(old_evergreen, now)
        assert score == pytest.approx(1.0)

    def test_access_count_boosts_score(self):
        now = time.time()
        ts = now - 10 * 86400
        high_access = {"ts": ts, "access_count": 10, "evergreen": False}
        low_access = {"ts": ts, "access_count": 0, "evergreen": False}
        assert _relevance_score(high_access, now) > _relevance_score(low_access, now)

    def test_score_formula_concrete_values(self):
        now = 1000000.0
        entry_age0 = {"ts": now, "access_count": 0, "evergreen": False}
        assert _relevance_score(entry_age0, now) == pytest.approx(1.0)

        entry_age30 = {"ts": now - 30 * 86400, "access_count": 0, "evergreen": False}
        assert _relevance_score(entry_age30, now) == pytest.approx(0.5)


class TestGetSummaryScored:
    def test_summary_ordered_by_relevance(self, mem, monkeypatch):
        now = time.time()
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now - 90 * 86400)
        mem.remember("fact", "Old fact", key="old")
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now)
        mem.remember("fact", "New fact", key="new")
        summary = mem.get_summary()
        lines = summary.split("\n")
        new_idx = next(i for i, l in enumerate(lines) if "New fact" in l)
        old_idx = next(i for i, l in enumerate(lines) if "Old fact" in l)
        assert new_idx < old_idx

    def test_evergreen_old_entry_ranks_high(self, mem, monkeypatch):
        now = time.time()
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now - 180 * 86400)
        mem.remember("fact", "Evergreen fact", key="eg", evergreen=True)
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now - 30 * 86400)
        mem.remember("fact", "Recent fact", key="recent")
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now)
        summary = mem.get_summary()
        lines = summary.split("\n")
        eg_idx = next(i for i, l in enumerate(lines) if "Evergreen fact" in l)
        recent_idx = next(i for i, l in enumerate(lines) if "Recent fact" in l)
        assert eg_idx < recent_idx

    def test_access_count_incremented_on_summary(self, mem):
        mem.remember("fact", "Check access", key="ac")
        data_before = mem.get_all()
        before_count = data_before["long_term"][0]["access_count"]
        mem.get_summary()
        data_after = mem.get_all()
        after_count = data_after["long_term"][0]["access_count"]
        assert after_count == before_count + 1

    def test_summary_includes_context(self, mem):
        mem.remember("preference", "No gluten", key="gluten", context="dietary needs")
        summary = mem.get_summary()
        assert "| context: dietary needs" in summary

    def test_summary_overflow_still_works(self, mem):
        for i in range(15):
            mem.remember("fact", f"Fact {i}", key=f"f-{i}")
        summary = mem.get_summary(max_items=10)
        assert "... and 5 more" in summary


class TestPromotion:
    def test_promote_conversations_at_threshold(self, mem):
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "knee pain exercises")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "knee pain exercises" in e["value"]]
        assert len(promoted) == 1
        assert promoted[0]["category"] == "fact"

    def test_no_promote_below_threshold(self, mem):
        for _ in range(PROMOTION_THRESHOLD - 1):
            mem.track("recent_conversations", "shoulder stretch")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "shoulder stretch" in e["value"]]
        assert len(promoted) == 0

    def test_promote_deduplicates(self, mem):
        mem.remember("fact", "knee pain exercises", key="existing-knee")
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "knee pain exercises")
        mem.get_summary()
        data = mem.get_all()
        matches = [e for e in data["long_term"] if "knee pain exercises" in e["value"]]
        assert len(matches) == 1  # No duplicate

    def test_promote_removes_short_term_entries(self, mem):
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "knee pain exercises")
        mem.get_summary()
        data = mem.get_all()
        st_values = [e["value"] for e in data["short_term"]["recent_conversations"]]
        assert "knee pain exercises" not in st_values

    def test_promote_sets_context(self, mem):
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "protein intake")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "protein intake" in e["value"]]
        assert len(promoted) == 1
        assert promoted[0]["context"] == "Auto-promoted from repeated recent_conversations"

    def test_no_promotion_from_recent_plans(self, mem):
        """recent_plans entries should never be promoted even if repeated."""
        for _ in range(PROMOTION_THRESHOLD + 2):
            mem.track("recent_plans", "5-day strength routine")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "5-day strength routine" in e["value"]]
        assert len(promoted) == 0

    def test_no_promotion_from_health_status(self, mem):
        """health_status entries should never be promoted even if repeated."""
        for _ in range(PROMOTION_THRESHOLD + 2):
            mem.track("health_status", "BMI 24.5")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "BMI 24.5" in e["value"]]
        assert len(promoted) == 0


# ===========================================================================
# 8. Migration tests
# ===========================================================================

class TestMigration:
    def test_old_short_term_categories_dropped_on_load(self, tmp_path):
        """Files with old categories (page_visits, etc.) should have them removed."""
        mem = UserMemory("migrator")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        old_data = {
            "short_term": {
                "page_visits": [{"key": "pv1", "value": "/settings", "ts": time.time(), "ttl": 604800}],
                "chat_topics": [{"key": "ct1", "value": "diet tips", "ts": time.time(), "ttl": 604800}],
                "recent_searches": [{"key": "rs1", "value": "bicep curls", "ts": time.time(), "ttl": 604800}],
                "last_used_skills": [{"key": "ls1", "value": "workout", "ts": time.time(), "ttl": 604800}],
            },
            "long_term": [],
        }
        mem.path.write_text(json.dumps(old_data), encoding="utf-8")
        data = mem.get_all()
        # Old categories should be gone
        for old_cat in _OLD_SHORT_TERM_CATEGORIES:
            assert old_cat not in data["short_term"]
        # New categories should exist (empty)
        for cat in SHORT_TERM_CATEGORIES:
            assert cat in data["short_term"]
            assert isinstance(data["short_term"][cat], list)

    def test_page_visit_promoted_noise_cleaned_on_load(self, tmp_path):
        """Long-term entries auto-promoted from page_visits should be removed."""
        mem = UserMemory("noisy")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        noisy_data = {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": [
                {
                    "key": "promoted-abc",
                    "category": "fact",
                    "value": "frequently uses settings",
                    "notes": None,
                    "context": "Auto-promoted from repeated page_visits",
                    "evergreen": False,
                    "access_count": 2,
                    "ts": time.time(),
                    "ttl": None,
                },
                {
                    "key": "real-fact",
                    "category": "fact",
                    "value": "Allergic to peanuts",
                    "notes": None,
                    "context": "dietary needs",
                    "evergreen": True,
                    "access_count": 5,
                    "ts": time.time(),
                    "ttl": None,
                },
            ],
        }
        mem.path.write_text(json.dumps(noisy_data), encoding="utf-8")
        data = mem.get_all()
        assert len(data["long_term"]) == 1
        assert data["long_term"][0]["key"] == "real-fact"

    def test_mixed_old_and_new_categories_migration(self, tmp_path):
        """If a file has a mix of old and new categories, old are dropped, new are preserved."""
        mem = UserMemory("mixed")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mixed_data = {
            "short_term": {
                "page_visits": [{"key": "pv1", "value": "/home", "ts": time.time(), "ttl": 604800}],
                "recent_conversations": [{"key": "rc1", "value": "asked about diet", "ts": time.time(), "ttl": 604800}],
            },
            "long_term": [],
        }
        mem.path.write_text(json.dumps(mixed_data), encoding="utf-8")
        data = mem.get_all()
        assert "page_visits" not in data["short_term"]
        assert len(data["short_term"]["recent_conversations"]) == 1
        assert data["short_term"]["recent_conversations"][0]["value"] == "asked about diet"
        # Ensure all new categories exist
        for cat in SHORT_TERM_CATEGORIES:
            assert cat in data["short_term"]


class TestAPINewFields:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from flask import Flask
        from flask_login import LoginManager
        from functions.user_memory import memory_bp

        app = Flask(__name__)
        app.secret_key = "test-secret"
        lm = LoginManager()
        lm.init_app(app)
        lm.user_loader(lambda uid: None)
        app.register_blueprint(memory_bp)
        app.config["TESTING"] = True
        return app.test_client()

    @staticmethod
    def _login(client, username="apiuser"):
        with client.session_transaction() as sess:
            sess["username"] = username

    def test_api_accepts_context_and_evergreen(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "preference",
            "value": "Low carb",
            "key": "diet",
            "context": "nutrition plan",
            "evergreen": True,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["entry"]["context"] == "nutrition plan"
        assert body["entry"]["evergreen"] is True

    def test_api_rejects_long_context(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
            "context": "x" * 501,
        })
        assert resp.status_code == 400

    def test_api_rejects_non_bool_evergreen(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
            "evergreen": "yes",
        })
        assert resp.status_code == 400

    def test_api_rejects_non_string_context(self, client):
        self._login(client)
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
            "context": 123,
        })
        assert resp.status_code == 400


# ===========================================================================
# 9. Additional coverage: gaps identified by adversarial review
# ===========================================================================


class TestMigrationAdditional:
    """Additional migration edge cases beyond the basics."""

    def test_file_with_only_old_categories_gets_new_ones(self, tmp_path):
        """A file that has ONLY old categories (no new ones at all) should heal."""
        mem = UserMemory("onlyold")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        old_only = {
            "short_term": {
                "page_visits": [{"key": "pv1", "value": "/home", "ts": time.time(), "ttl": 604800}],
                "chat_topics": [{"key": "ct1", "value": "nutrition", "ts": time.time(), "ttl": 604800}],
            },
            "long_term": [],
        }
        mem.path.write_text(json.dumps(old_only), encoding="utf-8")
        data = mem.get_all()
        for old_cat in _OLD_SHORT_TERM_CATEGORIES:
            assert old_cat not in data["short_term"]
        for cat in SHORT_TERM_CATEGORIES:
            assert cat in data["short_term"]
            assert data["short_term"][cat] == []

    def test_multiple_page_visit_noise_entries_all_removed(self, tmp_path):
        """Multiple long-term entries promoted from page_visits should all be removed."""
        mem = UserMemory("multinoise")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        noisy_data = {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": [
                {
                    "key": f"promoted-{i}",
                    "category": "fact",
                    "value": f"page visit noise {i}",
                    "notes": None,
                    "context": "Auto-promoted from repeated page_visits",
                    "evergreen": False,
                    "access_count": 0,
                    "ts": time.time(),
                    "ttl": None,
                }
                for i in range(5)
            ] + [
                {
                    "key": "legit",
                    "category": "preference",
                    "value": "Likes running",
                    "notes": None,
                    "context": None,
                    "evergreen": False,
                    "access_count": 0,
                    "ts": time.time(),
                    "ttl": None,
                },
            ],
        }
        mem.path.write_text(json.dumps(noisy_data), encoding="utf-8")
        data = mem.get_all()
        assert len(data["long_term"]) == 1
        assert data["long_term"][0]["key"] == "legit"

    def test_legitimate_conversation_promoted_entries_survive_migration(self, tmp_path):
        """Entries promoted from recent_conversations should NOT be removed."""
        mem = UserMemory("legit_promote")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": [
                {
                    "key": "promoted-conv",
                    "category": "fact",
                    "value": "knee pain exercises",
                    "notes": None,
                    "context": "Auto-promoted from repeated recent_conversations",
                    "evergreen": False,
                    "access_count": 0,
                    "ts": time.time(),
                    "ttl": None,
                },
            ],
        }
        mem.path.write_text(json.dumps(data), encoding="utf-8")
        loaded = mem.get_all()
        assert len(loaded["long_term"]) == 1
        assert loaded["long_term"][0]["value"] == "knee pain exercises"

    def test_migration_preserves_new_category_data(self, tmp_path):
        """Old category removal must not destroy data in valid new categories."""
        mem = UserMemory("preserve")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mixed = {
            "short_term": {
                "page_visits": [{"key": "pv1", "value": "/x", "ts": time.time(), "ttl": 604800}],
                "recent_conversations": [
                    {"key": "rc1", "value": "topic A", "ts": time.time(), "ttl": 604800},
                    {"key": "rc2", "value": "topic B", "ts": time.time(), "ttl": 604800},
                ],
                "recent_plans": [
                    {"key": "rp1", "value": "plan 1", "ts": time.time(), "ttl": 604800},
                ],
                "health_status": [
                    {"key": "hs1", "value": "BMI 22", "ts": time.time(), "ttl": 604800},
                ],
            },
            "long_term": [],
        }
        mem.path.write_text(json.dumps(mixed), encoding="utf-8")
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 2
        assert len(data["short_term"]["recent_plans"]) == 1
        assert len(data["short_term"]["health_status"]) == 1

    def test_migration_handles_old_category_with_non_list_value(self, tmp_path):
        """If an old category has a non-list value, migration still drops it cleanly."""
        mem = UserMemory("badold")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "short_term": {
                "page_visits": "not a list",
                "chat_topics": 42,
                "recent_conversations": [],
            },
            "long_term": [],
        }
        mem.path.write_text(json.dumps(data), encoding="utf-8")
        loaded = mem.get_all()
        assert "page_visits" not in loaded["short_term"]
        assert "chat_topics" not in loaded["short_term"]
        for cat in SHORT_TERM_CATEGORIES:
            assert cat in loaded["short_term"]


class TestPromotionAdditional:
    """Additional promotion edge cases."""

    def test_multiple_topics_promoted_simultaneously(self, mem):
        """Two different topics both above threshold should both be promoted."""
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "topic A")
            mem.track("recent_conversations", "topic B")
        mem.get_summary()
        data = mem.get_all()
        promoted_values = [e["value"] for e in data["long_term"]]
        assert "topic A" in promoted_values
        assert "topic B" in promoted_values

    def test_promotion_returns_promoted_keys(self, mem):
        """_promote() should return the keys of promoted entries."""
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "repeat topic")
        with mem._lock:
            data = mem._load()
            keys = mem._promote(data)
        assert len(keys) == 1
        assert keys[0].startswith("promoted-")

    def test_promotion_idempotent_on_repeated_summary(self, mem):
        """Calling get_summary() twice should not create duplicate long-term entries."""
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "stable topic")
        mem.get_summary()
        mem.get_summary()
        data = mem.get_all()
        matches = [e for e in data["long_term"] if e["value"] == "stable topic"]
        assert len(matches) == 1

    def test_promotion_threshold_exact_boundary(self, mem):
        """Exactly PROMOTION_THRESHOLD repetitions should trigger promotion."""
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "boundary topic")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if e["value"] == "boundary topic"]
        assert len(promoted) == 1

    def test_no_promotion_returns_empty_list(self, mem):
        """_promote() with nothing to promote returns an empty list."""
        mem.track("recent_conversations", "single mention")
        with mem._lock:
            data = mem._load()
            keys = mem._promote(data)
        assert keys == []

    def test_promoted_entry_has_correct_category(self, mem):
        """Promoted entries should always have category 'fact'."""
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "fact-worthy topic")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if e["value"] == "fact-worthy topic"]
        assert promoted[0]["category"] == "fact"

    def test_promoted_entry_has_null_ttl(self, mem):
        """Promoted entries should be permanent (ttl=None)."""
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("recent_conversations", "permanent topic")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if e["value"] == "permanent topic"]
        assert promoted[0]["ttl"] is None


class TestSummaryAdditional:
    """Additional summary rendering tests."""

    def test_summary_does_not_include_old_category_headings(self, mem):
        """Summary should never contain headings for old categories."""
        mem.track("recent_conversations", "something")
        summary = mem.get_summary()
        assert "Page visits" not in summary
        assert "page_visits" not in summary
        assert "Chat topics" not in summary
        assert "chat_topics" not in summary
        assert "Recent searches" not in summary
        assert "recent_searches" not in summary
        assert "Last used skills" not in summary
        assert "last_used_skills" not in summary

    def test_summary_section_headings_correct(self, mem):
        """Verify the exact section headings for each new category."""
        mem.track("recent_conversations", "conv topic")
        mem.track("recent_plans", "my plan")
        mem.track("health_status", "my health")
        summary = mem.get_summary()
        assert "Recent conversations:" in summary
        assert "Active plans:" in summary
        assert "Recent health status:" in summary

    def test_summary_with_only_short_term_no_long_term(self, mem):
        """Summary with only short-term entries should not have 'Long-term memories:' heading."""
        mem.track("recent_conversations", "just chatting")
        summary = mem.get_summary()
        assert "Long-term memories:" not in summary
        assert "Recent conversations:" in summary
        assert "just chatting" in summary

    def test_summary_with_only_long_term_no_short_term(self, mem):
        """Summary with only long-term entries should not have short-term headings."""
        mem.remember("preference", "Dark mode", key="theme")
        summary = mem.get_summary()
        assert "Long-term memories:" in summary
        assert "Recent conversations:" not in summary
        assert "Active plans:" not in summary
        assert "Recent health status:" not in summary

    def test_summary_max_items_shared_between_long_and_short(self, mem):
        """max_items budget is shared: long-term fills first, short-term gets the rest."""
        for i in range(8):
            mem.remember("fact", f"Fact {i}", key=f"f-{i}")
        mem.track("recent_conversations", "conv topic")
        mem.track("recent_plans", "plan topic")
        # max_items=10: 8 long-term + 2 short-term should all fit
        summary = mem.get_summary(max_items=10)
        assert "conv topic" in summary
        assert "plan topic" in summary

    def test_summary_max_items_1_shows_only_top_long_term(self, mem):
        """With max_items=1 and both long and short term, only top long-term entry shows."""
        mem.remember("preference", "VIP preference", key="vip")
        mem.track("recent_conversations", "conv topic")
        summary = mem.get_summary(max_items=1)
        assert "VIP preference" in summary
        # remaining budget is 0, so short-term should not appear
        assert "conv topic" not in summary


class TestEdgeCasesAdditional:
    """Additional edge cases for robustness."""

    def test_track_empty_string_value(self, mem):
        """Tracking an empty string should still work (no validation in track())."""
        entry = mem.track("recent_conversations", "")
        assert entry["value"] == ""

    def test_remember_very_long_value(self, mem):
        """Remember should handle values up to the normal Python string limit."""
        long_val = "x" * 10000
        entry = mem.remember("fact", long_val, key="long")
        assert entry["value"] == long_val

    def test_remember_unicode_value(self, mem):
        """Unicode values should be preserved correctly."""
        entry = mem.remember("fact", "Allergique aux arachides", key="unicode")
        data = mem.get_all()
        assert data["long_term"][0]["value"] == "Allergique aux arachides"

    def test_remember_emoji_value(self, mem):
        """Emoji characters should be preserved."""
        entry = mem.remember("fact", "Loves pizza", key="emoji")
        data = mem.get_all()
        assert "pizza" in data["long_term"][0]["value"]

    def test_file_is_array_not_dict(self, tmp_path):
        """If the file contains a JSON array instead of dict, it should recover."""
        mem = UserMemory("arraybug")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        data = mem.get_all()
        assert "short_term" in data
        assert "long_term" in data

    def test_file_is_null_json(self, tmp_path):
        """If the file contains 'null', it should recover."""
        mem = UserMemory("nulljson")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text("null", encoding="utf-8")
        data = mem.get_all()
        assert "short_term" in data
        assert "long_term" in data

    def test_file_is_integer_json(self, tmp_path):
        """If the file contains a bare integer, it should recover."""
        mem = UserMemory("intjson")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text("42", encoding="utf-8")
        data = mem.get_all()
        assert "short_term" in data
        assert "long_term" in data

    def test_short_term_category_replaced_with_non_list(self, tmp_path):
        """If a new short-term category has a non-list value, it should be healed to []."""
        mem = UserMemory("badcat")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "short_term": {
                "recent_conversations": "not a list",
                "recent_plans": 123,
                "health_status": None,
            },
            "long_term": [],
        }
        mem.path.write_text(json.dumps(data), encoding="utf-8")
        loaded = mem.get_all()
        for cat in SHORT_TERM_CATEGORIES:
            assert isinstance(loaded["short_term"][cat], list)

    def test_long_term_replaced_with_non_list_heals(self, tmp_path):
        """If long_term is a dict instead of list, it should be healed."""
        mem = UserMemory("badlt")
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "short_term": {cat: [] for cat in SHORT_TERM_CATEGORIES},
            "long_term": {"not": "a list"},
        }
        mem.path.write_text(json.dumps(data), encoding="utf-8")
        loaded = mem.get_all()
        assert isinstance(loaded["long_term"], list)

    def test_remember_old_short_term_category_as_long_term_rejected(self, mem):
        """Old short-term category names should be rejected as long-term categories too."""
        for old_cat in _OLD_SHORT_TERM_CATEGORIES:
            with pytest.raises(ValueError, match="Invalid long-term category"):
                mem.remember(old_cat, "something")

    def test_cleanup_does_not_touch_unexpired_entries(self, mem):
        """Cleanup should leave non-expired entries intact."""
        mem.track("recent_conversations", "topic A", ttl=99999)
        mem.track("recent_conversations", "topic B", ttl=99999)
        data = mem.get_all()
        assert len(data["short_term"]["recent_conversations"]) == 2


class TestAPIAdditional:
    """Additional API endpoint edge case tests."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from flask import Flask
        from flask_login import LoginManager
        from functions.user_memory import memory_bp

        app = Flask(__name__)
        app.secret_key = "test-secret"
        lm = LoginManager()
        lm.init_app(app)
        lm.user_loader(lambda uid: None)
        app.register_blueprint(memory_bp)
        app.config["TESTING"] = True
        return app.test_client()

    @staticmethod
    def _login(client, username="apiuser"):
        with client.session_transaction() as sess:
            sess["username"] = username

    def test_track_all_new_categories_accepted(self, client):
        """All new short-term categories should return 200 via the API."""
        self._login(client)
        for cat in SHORT_TERM_CATEGORIES:
            resp = client.post("/api/memory/track", json={
                "category": cat,
                "value": f"test-{cat}",
            })
            assert resp.status_code == 200, f"Category {cat} should be accepted"

    def test_track_empty_value_rejected(self, client):
        """Tracking empty value via API should return 400."""
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "",
        })
        assert resp.status_code == 400

    def test_track_whitespace_only_value_rejected(self, client):
        """Tracking whitespace-only value via API should return 400."""
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "   ",
        })
        assert resp.status_code == 400

    def test_remember_rejects_old_short_term_as_long_term(self, client):
        """Old short-term category names should be rejected in the remember API."""
        self._login(client)
        for old_cat in _OLD_SHORT_TERM_CATEGORIES:
            resp = client.post("/api/memory", json={
                "category": old_cat,
                "value": "something",
            })
            assert resp.status_code == 400, f"Old category {old_cat} should be rejected"

    def test_remember_rejects_new_short_term_categories(self, client):
        """New short-term categories should not be usable as long-term categories."""
        self._login(client)
        for cat in SHORT_TERM_CATEGORIES:
            resp = client.post("/api/memory", json={
                "category": cat,
                "value": "something",
            })
            assert resp.status_code == 400, f"Short-term category {cat} should be rejected for remember"

    def test_track_with_valid_ttl(self, client):
        """Track endpoint should accept a valid TTL value."""
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "topic with TTL",
            "ttl": 300,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["entry"]["ttl"] == 300

    def test_track_rejects_negative_ttl(self, client):
        """Track endpoint should reject negative TTL."""
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "negative TTL",
            "ttl": -1,
        })
        assert resp.status_code == 400

    def test_track_rejects_string_ttl(self, client):
        """Track endpoint should reject string TTL."""
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "recent_conversations",
            "value": "string TTL",
            "ttl": "forever",
        })
        assert resp.status_code == 400

    def test_forget_requires_auth(self, client):
        """Forget endpoint should require authentication."""
        resp = client.delete("/api/memory/some-key")
        assert resp.status_code == 401

    def test_remember_requires_auth(self, client):
        """Remember endpoint should require authentication."""
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "something",
        })
        assert resp.status_code == 401


class TestCategoryConstants:
    """Verify the category constants match the spec."""

    def test_short_term_categories_exact(self):
        assert SHORT_TERM_CATEGORIES == ["recent_conversations", "recent_plans", "health_status"]

    def test_long_term_categories_exact(self):
        assert LONG_TERM_CATEGORIES == ["preference", "fact", "saved", "goal"]

    def test_old_categories_exact(self):
        assert set(_OLD_SHORT_TERM_CATEGORIES) == {"page_visits", "chat_topics", "recent_searches", "last_used_skills"}

    def test_no_overlap_between_short_and_long_term(self):
        assert set(SHORT_TERM_CATEGORIES).isdisjoint(set(LONG_TERM_CATEGORIES))

    def test_no_overlap_between_new_and_old_short_term(self):
        assert set(SHORT_TERM_CATEGORIES).isdisjoint(set(_OLD_SHORT_TERM_CATEGORIES))

    def test_promotion_threshold_is_positive_integer(self):
        assert isinstance(PROMOTION_THRESHOLD, int)
        assert PROMOTION_THRESHOLD > 0

    def test_max_per_category_is_positive_integer(self):
        assert isinstance(MAX_PER_CATEGORY, int)
        assert MAX_PER_CATEGORY > 0

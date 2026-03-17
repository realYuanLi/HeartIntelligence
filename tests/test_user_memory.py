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
            mem.remember("page_visits", "something")

    def test_auto_generates_key_if_none(self, mem):
        entry = mem.remember("goal", "Run a marathon")
        assert entry["key"].startswith("goal-")
        assert len(entry["key"]) > len("goal-")

    def test_remember_with_ttl(self, mem):
        entry = mem.remember("saved", "Temporary bookmark", ttl=3600)
        assert entry["ttl"] == 3600


class TestTrack:
    def test_creates_short_term_entry(self, mem):
        entry = mem.track("page_visits", "/settings")
        assert entry["value"] == "/settings"
        assert "key" in entry
        assert "ts" in entry
        assert entry["ttl"] == DEFAULT_SHORT_TERM_TTL

    def test_custom_ttl(self, mem):
        entry = mem.track("chat_topics", "weather", ttl=120)
        assert entry["ttl"] == 120

    def test_stored_in_correct_category(self, mem):
        mem.track("recent_searches", "python decorators")
        data = mem.get_all()
        assert len(data["short_term"]["recent_searches"]) == 1
        assert data["short_term"]["recent_searches"][0]["value"] == "python decorators"

    def test_invalid_category_raises_value_error(self, mem):
        with pytest.raises(ValueError, match="Invalid short-term category"):
            mem.track("preference", "something")

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
        entry = mem.track("page_visits", "/dashboard")
        key = entry["key"]
        assert mem.forget(key) is True
        data = mem.get_all()
        assert len(data["short_term"]["page_visits"]) == 0

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
        mem.track("page_visits", "/home")
        data = mem.get_all()
        assert len(data["long_term"]) == 1
        assert len(data["short_term"]["page_visits"]) == 1


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

    def test_includes_recent_activity(self, mem):
        mem.track("chat_topics", "machine learning")
        summary = mem.get_summary()
        assert "Recent activity:" in summary
        assert "machine learning" in summary

    def test_max_items_limits_output(self, mem):
        for i in range(15):
            mem.remember("fact", f"Fact number {i}", key=f"fact-{i}")
        summary = mem.get_summary(max_items=5)
        assert "... and 10 more" in summary

    def test_summary_combines_topics_and_searches(self, mem):
        mem.track("chat_topics", "topic1")
        mem.track("recent_searches", "search1")
        summary = mem.get_summary()
        assert "topic1" in summary
        assert "search1" in summary


# ===========================================================================
# 2. TTL expiry tests
# ===========================================================================

class TestTTLExpiry:
    def test_expired_short_term_entry_removed(self, mem):
        """Entry with ttl=1 should be cleaned up after expiry."""
        entry = mem.track("page_visits", "/old-page", ttl=1)
        # Immediately after creation, it should exist
        data = mem.get_all()
        assert len(data["short_term"]["page_visits"]) == 1

        # Monkey-patch time to simulate passage
        real_time = time.time
        with patch("functions.user_memory.time") as mock_time:
            mock_time.time.return_value = real_time() + 2
            data = mem.get_all()
        assert len(data["short_term"]["page_visits"]) == 0

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
        mem.track("chat_topics", "ephemeral", ttl=0)
        # On next load, ts + 0 = ts, which is NOT > now, so it should be gone
        # (unless loaded in same instant). We patch time to be slightly ahead.
        real_time = time.time
        with patch("functions.user_memory.time") as mock_time:
            mock_time.time.return_value = real_time() + 0.001
            data = mem.get_all()
        assert len(data["short_term"]["chat_topics"]) == 0

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
            mem.track("page_visits", f"/page-{i}")
        data = mem.get_all()
        entries = data["short_term"]["page_visits"]
        assert len(entries) == MAX_PER_CATEGORY  # 20

    def test_oldest_entries_dropped(self, mem):
        """The 5 oldest entries (0-4) should be dropped when 25 are added."""
        for i in range(25):
            mem.track("page_visits", f"/page-{i}")
        data = mem.get_all()
        values = [e["value"] for e in data["short_term"]["page_visits"]]
        # Oldest 5 should be gone
        for i in range(5):
            assert f"/page-{i}" not in values
        # Newest should remain
        for i in range(5, 25):
            assert f"/page-{i}" in values

    def test_fifo_preserves_order(self, mem):
        """Entries should be in insertion order after pruning."""
        for i in range(25):
            mem.track("page_visits", f"/page-{i}")
        data = mem.get_all()
        values = [e["value"] for e in data["short_term"]["page_visits"]]
        expected = [f"/page-{i}" for i in range(5, 25)]
        assert values == expected


# ===========================================================================
# 4. Persistence tests
# ===========================================================================

class TestPersistence:
    def test_data_persists_across_instances(self, tmp_path):
        """New UserMemory instance for same user sees previous data."""
        mem1 = UserMemory("alice")
        mem1.remember("preference", "Likes cats", key="pet-pref")
        mem1.track("chat_topics", "feline health")

        # Create a fresh instance
        mem2 = UserMemory("alice")
        data = mem2.get_all()
        assert len(data["long_term"]) == 1
        assert data["long_term"][0]["value"] == "Likes cats"
        assert len(data["short_term"]["chat_topics"]) == 1

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
        # Should strip special chars, keep only alphanumeric, underscore, hyphen
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
        # Write garbage to the file
        mem.path.parent.mkdir(parents=True, exist_ok=True)
        mem.path.write_text("{{not valid json!!!", encoding="utf-8")
        # Should recover with default structure
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
            "short_term": {"page_visits": []},
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
        from functions.user_memory import memory_bp

        app = Flask(__name__)
        app.secret_key = "test-secret"
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
        # Create entry
        resp = client.post("/api/memory", json={
            "category": "fact",
            "value": "To be deleted",
            "key": "del-me",
        })
        assert resp.status_code == 200
        # Delete it
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
            "category": "page_visits",
            "value": "/dashboard",
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["entry"]["value"] == "/dashboard"

    def test_track_rejects_invalid_category(self, client):
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "preference",
            "value": "something",
        })
        assert resp.status_code == 400

    def test_track_rejects_long_value(self, client):
        self._login(client)
        resp = client.post("/api/memory/track", json={
            "category": "page_visits",
            "value": "x" * 201,
        })
        assert resp.status_code == 400

    def test_track_requires_auth(self, client):
        resp = client.post("/api/memory/track", json={
            "category": "page_visits",
            "value": "/home",
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
        # Simulate external access_count bump by modifying the file directly
        data = mem.get_all()
        for e in data["long_term"]:
            if e["key"] == "ac-test":
                e["access_count"] = 7
        mem._save(data)
        # Re-remember with same key (upsert)
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
        old_entry = {"ts": now - 60 * 86400, "access_count": 0, "evergreen": False}  # 60 days old
        assert _relevance_score(new_entry, now) > _relevance_score(old_entry, now)

    def test_evergreen_entries_get_max_decay(self):
        now = time.time()
        old_evergreen = {"ts": now - 365 * 86400, "access_count": 0, "evergreen": True}
        score = _relevance_score(old_evergreen, now)
        # Decay component should be 1.0, plus access_boost = log1p(0)*0.2 = 0
        assert score == pytest.approx(1.0)

    def test_access_count_boosts_score(self):
        now = time.time()
        ts = now - 10 * 86400  # 10 days old
        high_access = {"ts": ts, "access_count": 10, "evergreen": False}
        low_access = {"ts": ts, "access_count": 0, "evergreen": False}
        assert _relevance_score(high_access, now) > _relevance_score(low_access, now)

    def test_score_formula_concrete_values(self):
        now = 1000000.0
        # age=0 days → decay = exp(0) = 1.0
        entry_age0 = {"ts": now, "access_count": 0, "evergreen": False}
        assert _relevance_score(entry_age0, now) == pytest.approx(1.0)

        # age=30 days → decay = exp(-ln2 * 30/30) = exp(-ln2) = 0.5
        entry_age30 = {"ts": now - 30 * 86400, "access_count": 0, "evergreen": False}
        assert _relevance_score(entry_age30, now) == pytest.approx(0.5)


class TestGetSummaryScored:
    def test_summary_ordered_by_relevance(self, mem, monkeypatch):
        now = time.time()
        # Create old entry first
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now - 90 * 86400)
        mem.remember("fact", "Old fact", key="old")
        # Create new entry
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now)
        mem.remember("fact", "New fact", key="new")
        summary = mem.get_summary()
        lines = summary.split("\n")
        # New fact should appear before old fact
        new_idx = next(i for i, l in enumerate(lines) if "New fact" in l)
        old_idx = next(i for i, l in enumerate(lines) if "Old fact" in l)
        assert new_idx < old_idx

    def test_evergreen_old_entry_ranks_high(self, mem, monkeypatch):
        now = time.time()
        # Create old evergreen entry
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now - 180 * 86400)
        mem.remember("fact", "Evergreen fact", key="eg", evergreen=True)
        # Create newer non-evergreen entry (30 days old → decay ~0.5)
        monkeypatch.setattr("functions.user_memory.time.time", lambda: now - 30 * 86400)
        mem.remember("fact", "Recent fact", key="recent")
        # Restore time for get_summary
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
    def test_promote_at_threshold(self, mem):
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("page_visits", "/dashboard")
        # get_summary triggers _promote
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "dashboard" in e["value"]]
        assert len(promoted) == 1

    def test_no_promote_below_threshold(self, mem):
        for _ in range(PROMOTION_THRESHOLD - 1):
            mem.track("page_visits", "/settings")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "settings" in e["value"]]
        assert len(promoted) == 0

    def test_promote_deduplicates(self, mem):
        # Pre-create a long-term entry with the same value that promotion would create
        mem.remember("fact", "frequently uses /reports", key="existing-reports")
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("page_visits", "/reports")
        mem.get_summary()
        data = mem.get_all()
        matches = [e for e in data["long_term"] if "reports" in e["value"]]
        assert len(matches) == 1  # No duplicate

    def test_promote_removes_short_term_entries(self, mem):
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("page_visits", "/dashboard")
        mem.get_summary()
        data = mem.get_all()
        st_values = [e["value"] for e in data["short_term"]["page_visits"]]
        assert "/dashboard" not in st_values

    def test_promote_sets_context(self, mem):
        for _ in range(PROMOTION_THRESHOLD):
            mem.track("page_visits", "/analytics")
        mem.get_summary()
        data = mem.get_all()
        promoted = [e for e in data["long_term"] if "analytics" in e["value"]]
        assert len(promoted) == 1
        assert promoted[0]["context"] == "Auto-promoted from repeated page_visits"


class TestAPINewFields:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from flask import Flask
        from functions.user_memory import memory_bp

        app = Flask(__name__)
        app.secret_key = "test-secret"
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

"""Tests for exercise image display feature in WhatsApp integration.

Verifies that:
- handle_message returns a 3-tuple (reply, session_id, exercise_images)
- The /api/whatsapp/message endpoint includes exercise_images in its JSON response
- Empty exercise_images list when no exercises are found
- Error paths still return empty exercise_images
"""

import json
import sys
import types
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


# ---------------------------------------------------------------------------
# Mock the `app` module so deferred imports inside handle_message work.
# handle_message does `from app import Chatbot, PATIENT_DATA, system_prompt`
# and `from app import _generate_summary_async`.
# ---------------------------------------------------------------------------

_mock_app = types.ModuleType("app")
_mock_app.CONFIG = {"chatbot": {"prologue": "Hello!"}}
_mock_app.USERS = {"test": "test"}
_mock_app.PATIENT_DATA = {}
_mock_app.system_prompt = "You are a helpful assistant."
_mock_app.Chatbot = MagicMock()
_mock_app._generate_summary_async = MagicMock()
sys.modules.setdefault("app", _mock_app)

# Also mock functions.cron_jobs for create_reminder_from_chat
_mock_cron = types.ModuleType("functions.cron_jobs")
_mock_cron.create_reminder_from_chat = MagicMock(return_value=None)
sys.modules.setdefault("functions.cron_jobs", _mock_cron)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_resp(content: str, exercise_images: list | None = None):
    """Create a mock LLM response object with optional exercise_images."""
    resp = MagicMock()
    resp.content = content
    if exercise_images is not None:
        resp.exercise_images = exercise_images
    else:
        # Simulate attribute missing — getattr(..., default) returns default
        del resp.exercise_images
    return resp


@pytest.fixture(autouse=True)
def _reset_in_flight():
    """Ensure _in_flight set is clean before each test."""
    from whatsapp.flask_whatsapp import _in_flight
    saved = _in_flight.copy()
    _in_flight.clear()
    yield
    _in_flight.clear()
    _in_flight.update(saved)


# ---------------------------------------------------------------------------
# handle_message tests
# ---------------------------------------------------------------------------

class TestHandleMessageReturnsTuple:
    """handle_message must return (reply, session_id, exercise_images)."""

    @patch("whatsapp.flask_whatsapp._get_or_create_session", return_value="sess123")
    @patch("whatsapp.flask_whatsapp._load_chat")
    @patch("whatsapp.flask_whatsapp._save_chat")
    def test_returns_three_tuple_with_exercise_images(
        self, mock_save, mock_load, mock_session
    ):
        """When the LLM response has exercise_images, they appear in the third element."""
        mock_load.return_value = {
            "session_id": "sess123",
            "conversation": [
                {"role": "system", "content": "system prompt"},
                {"role": "assistant", "content": "Hello!"},
            ],
        }

        images = [
            {"name": "Push-up", "url": "/static/exercises/push_up.png"},
            {"name": "Squat", "url": "/static/exercises/squat.png"},
        ]
        mock_resp = _make_mock_resp("Here are some exercises.", images)
        _mock_app.Chatbot.llm_reply.return_value = mock_resp

        from whatsapp.flask_whatsapp import handle_message

        reply, session_id, exercise_images = handle_message(
            "test@jid", "Test User", "show me exercises"
        )

        assert reply == "Here are some exercises."
        assert session_id == "sess123"
        assert exercise_images == images
        assert len(exercise_images) == 2

    @patch("whatsapp.flask_whatsapp._get_or_create_session", return_value="sess456")
    @patch("whatsapp.flask_whatsapp._load_chat")
    @patch("whatsapp.flask_whatsapp._save_chat")
    def test_returns_empty_list_when_no_exercise_images(
        self, mock_save, mock_load, mock_session
    ):
        """When the LLM response has no exercise_images attr, return empty list."""
        mock_load.return_value = {
            "session_id": "sess456",
            "conversation": [
                {"role": "system", "content": "system prompt"},
                {"role": "assistant", "content": "Hello!"},
            ],
        }

        mock_resp = _make_mock_resp("Just a regular reply.")
        _mock_app.Chatbot.llm_reply.return_value = mock_resp

        from whatsapp.flask_whatsapp import handle_message

        reply, session_id, exercise_images = handle_message(
            "test2@jid", "Test User", "hello"
        )

        assert reply == "Just a regular reply."
        assert session_id == "sess456"
        assert exercise_images == []

    def test_in_flight_returns_empty_tuple(self):
        """When sender is already in-flight, return empty strings and empty list."""
        from whatsapp.flask_whatsapp import handle_message, _in_flight
        _in_flight.add("busy@jid")

        reply, session_id, exercise_images = handle_message(
            "busy@jid", "Busy User", "hello"
        )
        assert reply == ""
        assert session_id == ""
        assert exercise_images == []

    @patch("whatsapp.flask_whatsapp._get_or_create_session", return_value="sess789")
    @patch("whatsapp.flask_whatsapp._load_chat", return_value={})
    def test_missing_session_returns_empty_exercise_images(
        self, mock_load, mock_session
    ):
        """When session data is missing on disk, still returns 3-tuple with empty images."""
        from whatsapp.flask_whatsapp import handle_message

        reply, session_id, exercise_images = handle_message(
            "missing@jid", "Missing User", "hello"
        )

        assert "error" in reply.lower() or "Internal" in reply
        assert session_id == "sess789"
        assert exercise_images == []

    @patch("whatsapp.flask_whatsapp._get_or_create_session", side_effect=Exception("DB error"))
    def test_exception_returns_empty_exercise_images(self, mock_session):
        """On exception, still returns 3-tuple with empty exercise_images."""
        from whatsapp.flask_whatsapp import handle_message

        reply, session_id, exercise_images = handle_message(
            "error@jid", "Error User", "hello"
        )

        assert "trouble" in reply.lower() or "Sorry" in reply
        assert exercise_images == []


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestApiWhatsAppMessageEndpoint:
    """Test the /api/whatsapp/message Flask endpoint includes exercise_images."""

    @patch("whatsapp.flask_whatsapp._require_login", return_value=True)
    @patch("whatsapp.flask_whatsapp.handle_message")
    def test_endpoint_includes_exercise_images(self, mock_handle, mock_login):
        """When handle_message returns exercise_images, they appear in JSON response."""
        images = [{"name": "Lunge", "url": "/static/exercises/lunge.png"}]
        mock_handle.return_value = ("Do lunges!", "sess_abc", images)

        from flask import Flask
        from whatsapp.flask_whatsapp import whatsapp_bp

        app = Flask(__name__)
        app.register_blueprint(whatsapp_bp)

        with app.test_client() as client:
            resp = client.post(
                "/api/whatsapp/message",
                json={
                    "sender_jid": "user@jid",
                    "sender_name": "User",
                    "message": "show exercises",
                },
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["assistant_message"] == "Do lunges!"
        assert data["session_id"] == "sess_abc"
        assert data["exercise_images"] == images

    @patch("whatsapp.flask_whatsapp._require_login", return_value=True)
    @patch("whatsapp.flask_whatsapp.handle_message")
    def test_endpoint_omits_exercise_images_when_empty(self, mock_handle, mock_login):
        """When exercise_images is empty, it should not appear in the JSON response."""
        mock_handle.return_value = ("Hello!", "sess_def", [])

        from flask import Flask
        from whatsapp.flask_whatsapp import whatsapp_bp

        app = Flask(__name__)
        app.register_blueprint(whatsapp_bp)

        with app.test_client() as client:
            resp = client.post(
                "/api/whatsapp/message",
                json={
                    "sender_jid": "user@jid",
                    "sender_name": "User",
                    "message": "hello",
                },
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["assistant_message"] == "Hello!"
        # exercise_images should NOT be in response when empty
        assert "exercise_images" not in data

    @patch("whatsapp.flask_whatsapp._require_login", return_value=True)
    @patch("whatsapp.flask_whatsapp.handle_message")
    def test_endpoint_returns_429_when_in_flight(self, mock_handle, mock_login):
        """When handle_message returns empty reply (in-flight), endpoint returns 429."""
        mock_handle.return_value = ("", "", [])

        from flask import Flask
        from whatsapp.flask_whatsapp import whatsapp_bp

        app = Flask(__name__)
        app.register_blueprint(whatsapp_bp)

        with app.test_client() as client:
            resp = client.post(
                "/api/whatsapp/message",
                json={
                    "sender_jid": "user@jid",
                    "sender_name": "User",
                    "message": "hello",
                },
            )

        assert resp.status_code == 429
        data = resp.get_json()
        assert data["success"] is False

    @patch("whatsapp.flask_whatsapp._require_login", return_value=False)
    def test_endpoint_requires_login(self, mock_login):
        """Endpoint returns 401 when not logged in."""
        from flask import Flask
        from whatsapp.flask_whatsapp import whatsapp_bp

        app = Flask(__name__)
        app.register_blueprint(whatsapp_bp)

        with app.test_client() as client:
            resp = client.post(
                "/api/whatsapp/message",
                json={
                    "sender_jid": "user@jid",
                    "sender_name": "User",
                    "message": "hello",
                },
            )

        assert resp.status_code == 401

    @patch("whatsapp.flask_whatsapp._require_login", return_value=True)
    @patch("whatsapp.flask_whatsapp.handle_message")
    def test_endpoint_exercise_images_with_multiple_items(self, mock_handle, mock_login):
        """Verify multiple exercise images are returned correctly."""
        images = [
            {"name": "Push-up", "url": "/static/exercises/push_up.png"},
            {"name": "Squat", "url": "/static/exercises/squat.png"},
            {"name": "Lunge", "url": "/static/exercises/lunge.png"},
        ]
        mock_handle.return_value = ("Try these exercises!", "sess_multi", images)

        from flask import Flask
        from whatsapp.flask_whatsapp import whatsapp_bp

        app = Flask(__name__)
        app.register_blueprint(whatsapp_bp)

        with app.test_client() as client:
            resp = client.post(
                "/api/whatsapp/message",
                json={
                    "sender_jid": "user@jid",
                    "sender_name": "User",
                    "message": "exercises",
                },
            )

        data = resp.get_json()
        assert len(data["exercise_images"]) == 3
        assert data["exercise_images"][0]["name"] == "Push-up"
        assert data["exercise_images"][2]["url"] == "/static/exercises/lunge.png"


# ---------------------------------------------------------------------------
# Conversation storage tests
# ---------------------------------------------------------------------------

class TestExerciseImagesInConversation:
    """Verify exercise_images are stored in conversation history."""

    @patch("whatsapp.flask_whatsapp._get_or_create_session", return_value="sess_store")
    @patch("whatsapp.flask_whatsapp._load_chat")
    @patch("whatsapp.flask_whatsapp._save_chat")
    def test_exercise_images_saved_in_assistant_entry(
        self, mock_save, mock_load, mock_session
    ):
        """Assistant message in conversation should include exercise_images when present."""
        mock_load.return_value = {
            "session_id": "sess_store",
            "conversation": [
                {"role": "system", "content": "system prompt"},
                {"role": "assistant", "content": "Hello!"},
            ],
        }

        images = [{"name": "Plank", "url": "/static/exercises/plank.png"}]
        mock_resp = _make_mock_resp("Do a plank!", images)
        _mock_app.Chatbot.llm_reply.return_value = mock_resp

        from whatsapp.flask_whatsapp import handle_message

        handle_message("store@jid", "Store User", "show plank")

        # Check what was saved
        assert mock_save.called
        saved_data = mock_save.call_args[0][0]
        assistant_msgs = [
            m for m in saved_data["conversation"]
            if m.get("role") == "assistant"
        ]
        # The last assistant message should have exercise_images
        last_asst = assistant_msgs[-1]
        assert last_asst["exercise_images"] == images

    @patch("whatsapp.flask_whatsapp._get_or_create_session", return_value="sess_noimg")
    @patch("whatsapp.flask_whatsapp._load_chat")
    @patch("whatsapp.flask_whatsapp._save_chat")
    def test_no_exercise_images_key_when_empty(
        self, mock_save, mock_load, mock_session
    ):
        """Assistant message should NOT have exercise_images key when list is empty."""
        mock_load.return_value = {
            "session_id": "sess_noimg",
            "conversation": [
                {"role": "system", "content": "system prompt"},
                {"role": "assistant", "content": "Hello!"},
            ],
        }

        mock_resp = _make_mock_resp("Just chatting.")
        _mock_app.Chatbot.llm_reply.return_value = mock_resp

        from whatsapp.flask_whatsapp import handle_message

        handle_message("noimg@jid", "NoImg User", "hello")

        saved_data = mock_save.call_args[0][0]
        assistant_msgs = [
            m for m in saved_data["conversation"]
            if m.get("role") == "assistant"
        ]
        last_asst = assistant_msgs[-1]
        assert "exercise_images" not in last_asst

"""Comprehensive tests for the dreamchat CLI system.

Tests cover the HTTP client (DreamChatClient), CLI command dispatcher,
JSON output contract, and SKILL.md validation.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shlex
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from urllib.error import HTTPError, URLError

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dreamchat.client import DreamChatClient, load_config, save_config, load_session_state, save_session_state
from dreamchat.cli import build_parser, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockHTTPResponse:
    """Minimal mock of urllib response object."""

    def __init__(self, data: dict | str | bytes, status: int = 200):
        if isinstance(data, dict):
            self._body = json.dumps(data).encode()
        elif isinstance(data, str):
            self._body = data.encode()
        elif isinstance(data, bytes):
            self._body = data
        else:
            self._body = b""
        self.status = status
        self.code = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_http_error(code: int, body: str = "") -> HTTPError:
    """Create an HTTPError with a readable body."""
    err = HTTPError(
        url="http://test",
        code=code,
        msg=f"HTTP {code}",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode()),
    )
    return err


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Redirect all dreamchat config/session/cookie paths to tmp_path."""
    config_dir = tmp_path / ".dreamchat"
    config_dir.mkdir()
    os.chmod(config_dir, 0o700)

    config_file = config_dir / "config.json"
    cookie_file = config_dir / "cookies.txt"
    session_file = config_dir / "session.json"

    monkeypatch.setattr("dreamchat.client.CONFIG_DIR", config_dir)
    monkeypatch.setattr("dreamchat.client.CONFIG_FILE", config_file)
    monkeypatch.setattr("dreamchat.client.COOKIE_FILE", cookie_file)
    monkeypatch.setattr("dreamchat.client.SESSION_FILE", session_file)

    return {
        "dir": config_dir,
        "config": config_file,
        "cookie": cookie_file,
        "session": session_file,
    }


@pytest.fixture()
def client(tmp_config):
    """DreamChatClient with mocked opener and filesystem isolation."""
    c = DreamChatClient(
        base_url="http://localhost:8000",
        email="test@example.com",
        password="testpass",
    )
    c._opener = MagicMock()
    return c


# ═══════════════════════════════════════════════════════════════════════════
# 1. Client Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDreamChatClient:

    # -- Config: load empty, save/load roundtrip, session state -----------

    def test_load_config_empty(self, tmp_config):
        """Loading config when file does not exist returns empty dict."""
        assert load_config() == {}

    def test_save_load_config_roundtrip(self, tmp_config):
        """Config is saved and loaded faithfully."""
        cfg = {"base_url": "http://example.com", "email": "a@b.com", "password": "s3cret"}
        save_config(cfg)
        loaded = load_config()
        assert loaded == cfg

    def test_config_file_permissions(self, tmp_config):
        """Config file should have 0600 permissions."""
        save_config({"key": "value"})
        stat = os.stat(tmp_config["config"])
        assert oct(stat.st_mode & 0o777) == "0o600"

    def test_session_state_save_load(self, tmp_config):
        """Session state round-trips through save/load."""
        state = {"session_id": "abc-123", "extra": True}
        save_session_state(state)
        loaded = load_session_state()
        assert loaded == state

    def test_session_state_empty(self, tmp_config):
        """Loading session state when no file exists returns empty dict."""
        assert load_session_state() == {}

    # -- URL building -----------------------------------------------------

    def test_url_basic(self, client):
        assert client._url("/health") == "http://localhost:8000/health"

    def test_url_strips_trailing_slash(self, tmp_config):
        c = DreamChatClient(base_url="http://host:8000/", email="a", password="b")
        assert c._url("/api/test") == "http://host:8000/api/test"

    def test_url_subpath_deployment(self, tmp_config):
        c = DreamChatClient(base_url="http://host/dream", email="a", password="b")
        assert c._url("/api/health") == "http://host/dream/api/health"

    def test_url_subpath_with_trailing_slash(self, tmp_config):
        c = DreamChatClient(base_url="http://host/dream/", email="a", password="b")
        assert c._url("/api/health") == "http://host/dream/api/health"

    def test_url_double_slash_path(self, client):
        """Leading slashes in path should not produce double slashes."""
        url = client._url("//api/test")
        assert "//" not in url.split("://")[1]

    # -- Auth: login success, no credentials, HTTP error, connection ------

    def test_login_success(self, client, tmp_config):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "email": "test@example.com"}
        )
        # Should not raise
        client._login()
        client._opener.open.assert_called_once()

    def test_login_no_credentials(self, tmp_config):
        c = DreamChatClient(base_url="http://localhost:8000", email="", password="")
        with pytest.raises(SystemExit, match="No credentials"):
            c._login()

    def test_login_http_error(self, client):
        client._opener.open.side_effect = _make_http_error(403, "Forbidden")
        with pytest.raises(SystemExit, match="Login failed.*403"):
            client._login()

    def test_login_connection_error(self, client):
        client._opener.open.side_effect = URLError("Connection refused")
        with pytest.raises(SystemExit, match="Cannot reach server"):
            client._login()

    def test_login_server_rejects(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": False, "message": "Invalid credentials"}
        )
        with pytest.raises(SystemExit, match="Login failed.*Invalid"):
            client._login()

    # -- Auto-reauth: 401 triggers login + retry; no infinite loop --------

    def test_auto_reauth_on_401(self, client):
        """401 triggers _login then retries the request once."""
        call_count = 0

        def open_side_effect(req, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call to _request raises 401
            if call_count == 1:
                raise _make_http_error(401, '{"message": "unauthorized"}')
            # Login call (second call) succeeds
            if call_count == 2:
                return MockHTTPResponse({"success": True})
            # Retry call (third call) succeeds
            return MockHTTPResponse({"data": "ok"})

        client._opener.open.side_effect = open_side_effect
        result = client._get("/api/test")
        assert result == {"data": "ok"}
        assert call_count == 3  # original + login + retry

    def test_no_infinite_loop_on_repeated_401(self, client):
        """Repeated 401 after reauth does NOT loop infinitely."""
        call_count = 0

        def open_side_effect(req, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Login succeeds
                return MockHTTPResponse({"success": True})
            # All other calls return 401
            raise _make_http_error(401, '{"message": "still unauthorized"}')

        client._opener.open.side_effect = open_side_effect
        result = client._get("/api/test")
        # Should get the error response, not loop
        assert result == {"message": "still unauthorized"}
        assert call_count == 3  # original 401 + login + retry 401

    # -- Server status: healthy, unreachable, non-JSON --------------------

    def test_server_status_healthy(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"status": "healthy", "version": "1.0"}
        )
        result = client.server_status()
        assert result["status"] == "healthy"

    def test_server_status_unreachable(self, client):
        client._opener.open.side_effect = URLError("Connection refused")
        result = client.server_status()
        assert result["status"] == "unreachable"
        assert "error" in result

    def test_server_status_non_json(self, client):
        client._opener.open.return_value = MockHTTPResponse(b"<html>Bad Gateway</html>")
        result = client.server_status()
        assert result["status"] == "unknown"
        assert "Non-JSON" in result.get("error", "")

    # -- API methods -------------------------------------------------------

    def test_health_data(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "data": {"heart_rate": {"has_data": True}}}
        )
        result = client.health_data()
        assert result["success"] is True

    def test_patient_info(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "patient": {"name": "Test"}}
        )
        result = client.patient_info()
        assert result["success"] is True

    def test_cron_jobs(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "jobs": [{"job_id": "1", "message": "Take meds"}]}
        )
        result = client.cron_jobs()
        assert result["success"] is True
        assert len(result["jobs"]) == 1

    def test_heartbeat_status(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "status": {"enabled": True, "messages_today": 3}}
        )
        result = client.heartbeat_status()
        assert result["success"] is True

    def test_new_session(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "session_id": "sess-new-1"}
        )
        result = client.new_session()
        assert result["session_id"] == "sess-new-1"

    def test_get_session(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "conversation": [{"role": "user", "content": "hi"}]}
        )
        result = client.get_session("sess-123")
        assert result["success"] is True
        assert len(result["conversation"]) == 1

    def test_send_message_text_only(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "assistant_message": "Hello!"}
        )
        result = client.send_message("sess-1", "Hello")
        assert result["assistant_message"] == "Hello!"

    def test_send_message_with_images(self, client):
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "assistant_message": "Nice food!"}
        )
        result = client.send_message("sess-1", "What is this?", images=["data:image/jpeg;base64,abc"])
        assert result["success"] is True

    def test_request_connection_error(self, client):
        """Connection error returns error dict instead of raising."""
        client._opener.open.side_effect = URLError("Network unreachable")
        result = client._get("/api/test")
        assert result["success"] is False
        assert "Connection error" in result["message"]

    def test_request_http_error_with_json_body(self, client):
        """Non-401 HTTP error with JSON body returns parsed JSON."""
        client._opener.open.side_effect = _make_http_error(
            500, json.dumps({"success": False, "message": "Internal error"})
        )
        result = client._get("/api/test")
        assert result["success"] is False
        assert result["message"] == "Internal error"

    def test_request_http_error_with_non_json_body(self, client):
        """Non-401 HTTP error with non-JSON body returns fallback dict."""
        client._opener.open.side_effect = _make_http_error(502, "<html>Bad Gateway</html>")
        result = client._get("/api/test")
        assert result["success"] is False
        assert "HTTP 502" in result["message"]

    # -- Session management ------------------------------------------------

    def test_ensure_session_valid(self, client, tmp_config):
        """When session file has a valid session_id, return it."""
        save_session_state({"session_id": "existing-sess"})
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "conversation": []}
        )
        sid = client.ensure_session()
        assert sid == "existing-sess"

    def test_ensure_session_invalid(self, client, tmp_config):
        """When stored session is invalid, create a new one."""
        save_session_state({"session_id": "stale-sess"})
        call_count = 0

        def open_side_effect(req, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_session returns failure
                return MockHTTPResponse({"success": False, "message": "not found"})
            # new_session returns success
            return MockHTTPResponse({"success": True, "session_id": "fresh-sess"})

        client._opener.open.side_effect = open_side_effect
        sid = client.ensure_session()
        assert sid == "fresh-sess"
        # Verify it was persisted
        state = load_session_state()
        assert state["session_id"] == "fresh-sess"

    def test_ensure_session_missing(self, client, tmp_config):
        """When no session state exists, create a new one."""
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "session_id": "brand-new"}
        )
        sid = client.ensure_session()
        assert sid == "brand-new"

    def test_reset_session(self, client, tmp_config):
        """reset_session creates a new session and persists it."""
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "session_id": "reset-sess"}
        )
        sid = client.reset_session()
        assert sid == "reset-sess"
        state = load_session_state()
        assert state["session_id"] == "reset-sess"

    def test_reset_session_create_fails(self, client, tmp_config):
        """reset_session raises SystemExit if server fails."""
        client._opener.open.return_value = MockHTTPResponse(
            {"success": False, "message": "server busy"}
        )
        with pytest.raises(SystemExit, match="Cannot create session"):
            client.reset_session()

    def test_ensure_session_create_fails(self, client, tmp_config):
        """ensure_session raises SystemExit if new session creation fails."""
        client._opener.open.return_value = MockHTTPResponse(
            {"success": False, "message": "server busy"}
        )
        with pytest.raises(SystemExit, match="Cannot create session"):
            client.ensure_session()

    # -- Chat: text, image, image not found, MIME types --------------------

    def test_chat_text_only(self, client, tmp_config):
        """Chat with text message only."""
        save_session_state({"session_id": "chat-sess"})
        call_count = 0

        def open_side_effect(req, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockHTTPResponse({"success": True, "conversation": []})
            return MockHTTPResponse({"success": True, "assistant_message": "Response!"})

        client._opener.open.side_effect = open_side_effect
        result = client.chat("What's my heart rate?")
        assert result["success"] is True
        assert result["assistant_message"] == "Response!"

    def test_chat_with_image(self, client, tmp_config, tmp_path):
        """Chat with an image encodes it as base64 data URI."""
        save_session_state({"session_id": "img-sess"})

        # Create a small test image file
        img_file = tmp_path / "food.png"
        img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20  # minimal PNG-like header
        img_file.write_bytes(img_bytes)

        call_count = 0

        def open_side_effect(req, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockHTTPResponse({"success": True, "conversation": []})
            # Verify the request body has the image
            body = json.loads(req.data.decode())
            assert "images" in body
            assert len(body["images"]) == 1
            assert body["images"][0].startswith("data:image/png;base64,")
            return MockHTTPResponse({"success": True, "assistant_message": "300 calories"})

        client._opener.open.side_effect = open_side_effect
        result = client.chat("How many calories?", image_path=str(img_file))
        assert result["success"] is True

    def test_chat_image_not_found(self, client, tmp_config):
        """Chat with nonexistent image returns error without calling API."""
        save_session_state({"session_id": "img-sess"})
        client._opener.open.return_value = MockHTTPResponse(
            {"success": True, "conversation": []}
        )
        result = client.chat("analyze this", image_path="/nonexistent/photo.jpg")
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_chat_mime_type_detection(self, client, tmp_config, tmp_path):
        """Different image extensions map to correct MIME types."""
        save_session_state({"session_id": "mime-sess"})

        cases = {
            "test.jpg": "jpeg",
            "test.jpeg": "jpeg",
            "test.png": "png",
            "test.gif": "gif",
            "test.webp": "webp",
            "test.bmp": "jpeg",  # unknown extension falls back to jpeg
        }

        for filename, expected_mime in cases.items():
            img_file = tmp_path / filename
            img_file.write_bytes(b"\x00" * 10)

            captured_body = {}

            def open_side_effect(req, **kwargs):
                if hasattr(req, "data") and req.data:
                    body = json.loads(req.data.decode())
                    if "images" in body:
                        captured_body["images"] = body["images"]
                return MockHTTPResponse({"success": True, "conversation": [], "session_id": "mime-sess", "assistant_message": "ok"})

            client._opener.open.side_effect = open_side_effect
            client.chat("test", image_path=str(img_file))

            assert "images" in captured_body, f"No images captured for {filename}"
            assert f"data:image/{expected_mime};base64," in captured_body["images"][0], \
                f"Expected mime '{expected_mime}' for {filename}"

    def test_chat_image_base64_encoding(self, client, tmp_config, tmp_path):
        """Image content is correctly base64 encoded."""
        save_session_state({"session_id": "b64-sess"})
        img_file = tmp_path / "pic.jpg"
        original_bytes = b"hello-image-content-1234567890"
        img_file.write_bytes(original_bytes)

        captured_uri = {}

        def open_side_effect(req, **kwargs):
            if hasattr(req, "data") and req.data:
                body = json.loads(req.data.decode())
                if "images" in body:
                    captured_uri["uri"] = body["images"][0]
            return MockHTTPResponse({"success": True, "conversation": [], "assistant_message": "ok"})

        client._opener.open.side_effect = open_side_effect
        client.chat("test", image_path=str(img_file))

        assert "uri" in captured_uri
        # Extract and decode base64
        prefix = "data:image/jpeg;base64,"
        b64_data = captured_uri["uri"][len(prefix):]
        decoded = base64.b64decode(b64_data)
        assert decoded == original_bytes


# ═══════════════════════════════════════════════════════════════════════════
# 2. CLI Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCLI:

    # -- Parser tests ------------------------------------------------------

    def test_parser_server_status(self):
        parser = build_parser()
        args = parser.parse_args(["server", "status"])
        assert args.command == "server"
        assert args.server_cmd == "status"

    def test_parser_health_status(self):
        parser = build_parser()
        args = parser.parse_args(["health", "status"])
        assert args.command == "health"
        assert args.health_cmd == "status"

    def test_parser_health_trends(self):
        parser = build_parser()
        args = parser.parse_args(["health", "trends"])
        assert args.command == "health"
        assert args.health_cmd == "trends"

    def test_parser_reminders_list(self):
        parser = build_parser()
        args = parser.parse_args(["reminders", "list"])
        assert args.command == "reminders"
        assert args.reminders_cmd == "list"

    def test_parser_heartbeat_status(self):
        parser = build_parser()
        args = parser.parse_args(["heartbeat", "status"])
        assert args.command == "heartbeat"
        assert args.heartbeat_cmd == "status"

    def test_parser_digest_daily(self):
        parser = build_parser()
        args = parser.parse_args(["digest", "daily"])
        assert args.command == "digest"
        assert args.digest_cmd == "daily"

    def test_parser_chat_ask(self):
        parser = build_parser()
        args = parser.parse_args(["chat", "ask", "What is my BP?"])
        assert args.command == "chat"
        assert args.chat_cmd == "ask"
        assert args.message == "What is my BP?"

    def test_parser_chat_ask_with_image(self):
        parser = build_parser()
        args = parser.parse_args(["chat", "ask", "calories?", "--image", "/tmp/food.jpg"])
        assert args.image == "/tmp/food.jpg"

    def test_parser_chat_history(self):
        parser = build_parser()
        args = parser.parse_args(["chat", "history"])
        assert args.chat_cmd == "history"

    def test_parser_chat_reset(self):
        parser = build_parser()
        args = parser.parse_args(["chat", "reset"])
        assert args.chat_cmd == "reset"

    def test_parser_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--json", "server", "status"])
        assert args.json is True

    def test_parser_no_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["server", "status"])
        assert args.json is False

    def test_parser_no_command_exits(self):
        """No command should exit with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_parser_unknown_command_exits(self):
        """Unknown command should exit with code 2 (argparse error)."""
        with pytest.raises(SystemExit):
            main(["nonexistent_command"])

    def test_parser_configure(self):
        parser = build_parser()
        args = parser.parse_args(["configure"])
        assert args.command == "configure"

    # -- JSON mode: server status ------------------------------------------

    def test_cmd_server_status_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.server_status.return_value = {"status": "healthy", "version": "1.0"}
            main(["--json", "server", "status"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["data"]["status"] == "healthy"

    # -- JSON mode: health status ------------------------------------------

    def test_cmd_health_status_json(self, capsys, tmp_config):
        mock_health = {
            "success": True,
            "data": {
                "heart_rate": {
                    "has_data": True,
                    "daily_stats": [{"date": "2026-03-30", "avg": 72, "min": 58, "max": 120}],
                },
                "blood_pressure": {
                    "has_data": True,
                    "readings": [{"systolic": 120, "diastolic": 80}],
                },
                "hrv": {
                    "has_data": True,
                    "daily_averages": [{"date": "2026-03-30", "avg": 45}],
                },
                "activity": {
                    "has_data": True,
                    "daily_steps": [{"date": "2026-03-30", "steps": 8500}],
                },
                "date_range": {"start": "2026-03-23", "end": "2026-03-30"},
            },
        }
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = mock_health
            main(["--json", "health", "status"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "heart_rate" in data["data"]
        assert "blood_pressure" in data["data"]
        assert "steps" in data["data"]

    # -- JSON mode: health trends ------------------------------------------

    def test_cmd_health_trends_json(self, capsys, tmp_config):
        mock_health = {
            "success": True,
            "data": {
                "heart_rate": {"has_data": True, "trends": {"direction": "stable"}},
                "activity": {"has_data": True, "trends": {"avg_steps": 9000}},
                "date_range": {"start": "2026-03-23", "end": "2026-03-30"},
            },
        }
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = mock_health
            main(["--json", "health", "trends"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "heart_rate" in data["data"]

    # -- JSON mode: reminders list -----------------------------------------

    def test_cmd_reminders_list_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.cron_jobs.return_value = {
                "success": True,
                "jobs": [
                    {"job_id": "1", "message": "Take medicine", "schedule_type": "daily",
                     "enabled": True, "time_of_day": "08:00", "frequency": "daily"},
                    {"job_id": "2", "message": "Exercise", "schedule_type": "daily",
                     "enabled": False, "time_of_day": "17:00", "frequency": "daily"},
                ],
            }
            main(["--json", "reminders", "list"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        assert len(data["data"]["reminders"]) == 2

    # -- JSON mode: heartbeat status ---------------------------------------

    def test_cmd_heartbeat_status_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.heartbeat_status.return_value = {
                "success": True,
                "status": {"enabled": True, "messages_today": 5, "last_message_preview": "Walk time!"},
            }
            main(["--json", "heartbeat", "status"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["data"]["enabled"] is True

    # -- JSON mode: digest daily -------------------------------------------

    def test_cmd_digest_daily_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = {
                "success": True,
                "data": {
                    "heart_rate": {"has_data": True, "daily_stats": [{"date": "2026-03-30", "avg": 72}]},
                    "blood_pressure": {"has_data": True, "readings": [{"systolic": 120, "diastolic": 80}]},
                    "activity": {"has_data": True, "daily_steps": [{"date": "2026-03-30", "steps": 9000}]},
                },
            }
            instance.cron_jobs.return_value = {
                "success": True,
                "jobs": [
                    {"job_id": "1", "message": "Take medicine", "enabled": True, "time_of_day": "08:00"},
                ],
            }
            instance.heartbeat_status.return_value = {
                "success": True,
                "status": {"enabled": True, "messages_today": 3, "last_message_preview": "Walk!"},
            }
            main(["--json", "digest", "daily"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "health_metrics" in data["data"]
        assert "active_reminders" in data["data"]
        assert "heartbeat" in data["data"]
        assert "generated_at" in data["data"]

    # -- JSON mode: chat ask -----------------------------------------------

    def test_cmd_chat_ask_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.chat.return_value = {
                "success": True,
                "assistant_message": "Your heart rate is 72 bpm, which is normal.",
            }
            main(["--json", "chat", "ask", "What is my heart rate?"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "72 bpm" in data["data"]["response"]

    # -- JSON mode: chat history -------------------------------------------

    def test_cmd_chat_history_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.ensure_session.return_value = "hist-sess"
            instance.get_session.return_value = {
                "success": True,
                "conversation": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
            }
            main(["--json", "chat", "history"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["data"]["session_id"] == "hist-sess"
        assert len(data["data"]["messages"]) == 2

    # -- JSON mode: chat reset ---------------------------------------------

    def test_cmd_chat_reset_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.reset_session.return_value = "new-sess-id"
            main(["--json", "chat", "reset"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["data"]["session_id"] == "new-sess-id"

    # -- Error paths -------------------------------------------------------

    def test_cmd_server_unreachable_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.server_status.return_value = {
                "status": "unreachable",
                "error": "Connection refused",
            }
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "server", "status"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert "unreachable" in data["error"].lower()

    def test_cmd_health_data_unavailable_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = {
                "success": False,
                "message": "Health data not available",
            }
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "health", "status"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False

    def test_cmd_chat_no_message_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "chat", "ask"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert "no message" in data["error"].lower()

    def test_cmd_health_trends_unavailable_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = {
                "success": False,
                "message": "No health data synced",
            }
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "health", "trends"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False

    def test_cmd_reminders_error_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.cron_jobs.return_value = {
                "success": False,
                "message": "Not authenticated",
            }
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "reminders", "list"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False

    def test_cmd_heartbeat_error_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.heartbeat_status.return_value = {
                "success": False,
                "message": "Heartbeat not configured",
            }
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "heartbeat", "status"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False

    def test_cmd_chat_ask_failure_json(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.chat.return_value = {
                "success": False,
                "message": "Server error",
            }
            with pytest.raises(SystemExit) as exc_info:
                main(["--json", "chat", "ask", "test question"])
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False

    # -- Digest composite: all sections present ----------------------------

    def test_cmd_digest_all_sections(self, capsys, tmp_config):
        """Digest includes health_metrics, active_reminders, heartbeat, and generated_at."""
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = {
                "success": True,
                "data": {
                    "heart_rate": {"has_data": True, "daily_stats": [{"avg": 70}]},
                    "blood_pressure": {"has_data": False},
                    "activity": {"has_data": True, "daily_steps": [{"steps": 10000}]},
                },
            }
            instance.cron_jobs.return_value = {
                "success": True,
                "jobs": [
                    {"job_id": "r1", "message": "Stretch", "enabled": True, "time_of_day": "09:00"},
                    {"job_id": "r2", "message": "Disabled", "enabled": False, "time_of_day": "10:00"},
                ],
            }
            instance.heartbeat_status.return_value = {
                "success": True,
                "status": {"enabled": True, "messages_today": 2, "last_message_preview": "Drink water"},
            }
            main(["--json", "digest", "daily"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        digest = data["data"]

        # All required sections present
        assert "generated_at" in digest
        assert "health_metrics" in digest
        assert "active_reminders" in digest
        assert "upcoming" in digest
        assert "heartbeat" in digest

        # Health metrics contain expected keys
        assert "heart_rate_avg" in digest["health_metrics"]
        assert "steps" in digest["health_metrics"]

        # Active reminders count should be 1 (only enabled)
        assert digest["active_reminders"] == 1

        # Heartbeat info
        assert digest["heartbeat"]["enabled"] is True
        assert digest["heartbeat"]["messages_today"] == 2

    def test_cmd_digest_partial_failure(self, capsys, tmp_config):
        """Digest should still succeed even if some API calls fail."""
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.health_data.return_value = {"success": False}
            instance.cron_jobs.return_value = {"success": False}
            instance.heartbeat_status.return_value = {"success": False}
            main(["--json", "digest", "daily"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "generated_at" in data["data"]

    # -- Chat ask with exercise images -------------------------------------

    def test_cmd_chat_ask_with_exercise_images(self, capsys, tmp_config):
        """Chat ask response with exercise_images includes them in output."""
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.chat.return_value = {
                "success": True,
                "assistant_message": "Try these exercises:",
                "exercise_images": ["/static/exercises/pushup.gif"],
            }
            main(["--json", "chat", "ask", "What exercises for chest?"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "exercise_images" in data["data"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. SKILL.md Tests
# ═══════════════════════════════════════════════════════════════════════════

SKILL_MD_PATH = PROJECT_ROOT / "openclaw" / "skills" / "dreamchat" / "SKILL.md"


def test_skill_md_exists():
    """SKILL.md file exists at expected path."""
    assert SKILL_MD_PATH.exists(), f"SKILL.md not found at {SKILL_MD_PATH}"


def test_skill_md_yaml_frontmatter_valid():
    """YAML frontmatter is valid and contains required fields."""
    content = SKILL_MD_PATH.read_text()
    assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"

    # Extract frontmatter
    parts = content.split("---", 2)
    assert len(parts) >= 3, "SKILL.md must have opening and closing --- for frontmatter"

    yaml_text = parts[1]

    # Parse YAML -- use simple parsing to avoid yaml dependency
    assert "name:" in yaml_text, "Frontmatter must contain 'name' field"
    assert "description:" in yaml_text, "Frontmatter must contain 'description' field"

    # Verify name value
    for line in yaml_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("name:"):
            name_value = stripped.split(":", 1)[1].strip()
            assert name_value, "name field must not be empty"
            break

    # Verify metadata.openclaw.requires.bins
    assert "bins:" in yaml_text, "Frontmatter must specify required bins"
    assert "dreamchat" in yaml_text, "Required bins must include 'dreamchat'"


def test_skill_md_commands_parseable():
    """Commands documented in SKILL.md should be parseable by the CLI parser."""
    content = SKILL_MD_PATH.read_text()
    parser = build_parser()

    # Extract commands from code blocks (exec dreamchat ...)
    commands = re.findall(r'exec dreamchat (.+)', content)
    assert len(commands) > 0, "SKILL.md should contain at least one exec dreamchat command"

    for cmd_str in commands:
        # Strip placeholder parts that won't parse
        # e.g. --image /path/to/photo.jpg -> --image /tmp/x.jpg
        cmd_str = cmd_str.strip().strip('"').strip("'")
        cmd_str = re.sub(r'/path/to/photo\.jpg', '/tmp/photo.jpg', cmd_str)
        # Remove quoted question strings and replace with a simple one
        cmd_str = re.sub(r'"[^"]*\?"', '"test"', cmd_str)
        cmd_str = re.sub(r'"[^"]*"', '"test"', cmd_str)

        try:
            argv = shlex.split(cmd_str)
        except ValueError:
            continue

        # This should not raise
        args = parser.parse_args(argv)
        assert args.command is not None, f"Command '{cmd_str}' did not produce a valid command"


def test_skill_md_output_format_documented():
    """SKILL.md must document the JSON output contract."""
    content = SKILL_MD_PATH.read_text()

    # Must mention the success format
    assert '"ok": true' in content, "SKILL.md must document the ok:true format"
    assert '"ok": false' in content, "SKILL.md must document the ok:false format"
    assert '"data"' in content, "SKILL.md must document the data field"
    assert '"error"' in content, "SKILL.md must document the error field"


def test_skill_md_has_when_to_use():
    """SKILL.md should contain a 'When to use' section."""
    content = SKILL_MD_PATH.read_text()
    assert "when to use" in content.lower()


def test_skill_md_has_critical_rules():
    """SKILL.md should contain critical rules section."""
    content = SKILL_MD_PATH.read_text()
    assert "critical rules" in content.lower()
    # Should warn against adding own medical interpretation
    assert "never" in content.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 4. JSON output contract enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestJSONOutputContract:
    """Verify that all --json commands produce the correct envelope."""

    def _run_json_cmd(self, argv, capsys, tmp_config, expect_error=False):
        """Run a CLI command with --json and return parsed output."""
        try:
            main(["--json"] + argv)
        except SystemExit as e:
            if not expect_error:
                raise
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        return data

    def test_success_envelope(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.server_status.return_value = {"status": "healthy"}
            data = self._run_json_cmd(["server", "status"], capsys, tmp_config)
        assert "ok" in data
        assert data["ok"] is True
        assert "data" in data

    def test_error_envelope(self, capsys, tmp_config):
        with patch("dreamchat.cli.DreamChatClient") as MockClient:
            instance = MockClient.return_value
            instance.server_status.return_value = {
                "status": "unreachable", "error": "Connection refused"
            }
            data = self._run_json_cmd(
                ["server", "status"], capsys, tmp_config, expect_error=True
            )
        assert "ok" in data
        assert data["ok"] is False
        assert "error" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

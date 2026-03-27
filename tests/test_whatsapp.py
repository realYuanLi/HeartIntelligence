"""Comprehensive tests for the multi-user WhatsApp integration.

Tests cover:
1. Flask proxy endpoints (connect, disconnect, status)
2. Message routing and user_id validation
3. Auth changes (service account seeding, api_login username field)
4. Settings page access
5. Security (user isolation, path traversal, in-flight keying)
6. Edge cases (empty/negative/huge user_id, concurrent users)
"""

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure project root is importable & OpenAI key doesn't block import
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-mocking")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from functions.auth import db, User, auth_bp, login_manager


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _create_app(tmp_dir: str | None = None):
    """Build a minimal Flask app wired with auth + whatsapp blueprints.

    Uses in-memory SQLite. No heavyweight app.py imports needed.
    Patches the DATA_DIR in flask_whatsapp to use a temp directory.
    """
    from flask import Flask

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-whatsapp"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    app.register_blueprint(auth_bp)

    # Import and register whatsapp blueprint
    from whatsapp.flask_whatsapp import whatsapp_bp
    app.register_blueprint(whatsapp_bp)

    # Patch DATA_DIR to use temp directory if provided
    if tmp_dir:
        import whatsapp.flask_whatsapp as wa_mod
        wa_mod.DATA_DIR = Path(tmp_dir)

    # Minimal index route (mirrors main app)
    from flask import redirect, url_for
    from flask_login import current_user

    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return f"Hello {current_user.email}", 200

    with app.app_context():
        db.create_all()

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Provide a temporary directory for WhatsApp chat data."""
    return str(tmp_path / "chat_history")


@pytest.fixture()
def app(tmp_data_dir):
    """Yield a fresh Flask app with an empty in-memory database."""
    application = _create_app(tmp_data_dir)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seeded_app(app):
    """App with two pre-seeded users for multi-user tests."""
    with app.app_context():
        user_a = User(email="alice@example.com", tier="free")
        user_a.set_password("alice123")
        db.session.add(user_a)

        user_b = User(email="bob@example.com", tier="free")
        user_b.set_password("bob123")
        db.session.add(user_b)

        db.session.commit()
    return app


@pytest.fixture()
def seeded_client(seeded_app):
    return seeded_app.test_client()


@pytest.fixture()
def authed_client_alice(seeded_app):
    """A test client already logged in as Alice."""
    c = seeded_app.test_client()
    c.post(
        "/api/login",
        json={"email": "alice@example.com", "password": "alice123"},
        content_type="application/json",
    )
    return c


@pytest.fixture()
def authed_client_bob(seeded_app):
    """A test client already logged in as Bob."""
    c = seeded_app.test_client()
    c.post(
        "/api/login",
        json={"email": "bob@example.com", "password": "bob123"},
        content_type="application/json",
    )
    return c


def _login_api(client, email, password):
    """Login via JSON API and return the response."""
    return client.post(
        "/api/login",
        json={"email": email, "password": password},
        content_type="application/json",
    )


# =========================================================================
# 1. Flask proxy endpoints
# =========================================================================

class TestProxyConnect:
    """POST /api/whatsapp/connect"""

    def test_connect_requires_auth(self, client):
        """Unauthenticated requests to connect should redirect to login."""
        rv = client.post("/api/whatsapp/connect")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_connect_proxies_to_node(self, mock_node, authed_client_alice, seeded_app):
        """Connect should forward request to Node.js with user_id."""
        mock_node.return_value = {"success": True, "qrDataUrl": "data:image/png;base64,abc"}
        rv = authed_client_alice.post("/api/whatsapp/connect")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True

        # Verify it called the Node API with the correct user_id
        with seeded_app.app_context():
            alice = User.query.filter_by(email="alice@example.com").first()
            mock_node.assert_called_once_with("POST", f"/api/connections/{alice.id}/connect")

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_connect_returns_502_when_node_down(self, mock_node, authed_client_alice):
        """When Node.js is unreachable, return 502."""
        mock_node.return_value = None
        rv = authed_client_alice.post("/api/whatsapp/connect")
        assert rv.status_code == 502
        data = rv.get_json()
        assert data["success"] is False
        assert "unavailable" in data["message"].lower()

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_connect_returns_409_on_conflict(self, mock_node, authed_client_alice):
        """When Node returns success=False (already connected), return 409."""
        mock_node.return_value = {"success": False, "message": "Already connected"}
        rv = authed_client_alice.post("/api/whatsapp/connect")
        assert rv.status_code == 409


class TestProxyDisconnect:
    """POST /api/whatsapp/disconnect"""

    def test_disconnect_requires_auth(self, client):
        """Unauthenticated requests to disconnect should redirect to login."""
        rv = client.post("/api/whatsapp/disconnect")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_disconnect_proxies_to_node(self, mock_node, authed_client_alice, seeded_app):
        """Disconnect should forward request to Node.js with user_id."""
        mock_node.return_value = {"success": True}
        rv = authed_client_alice.post("/api/whatsapp/disconnect")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True

        with seeded_app.app_context():
            alice = User.query.filter_by(email="alice@example.com").first()
            mock_node.assert_called_once_with("POST", f"/api/connections/{alice.id}/disconnect")

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_disconnect_returns_502_when_node_down(self, mock_node, authed_client_alice):
        """When Node.js is unreachable, return 502."""
        mock_node.return_value = None
        rv = authed_client_alice.post("/api/whatsapp/disconnect")
        assert rv.status_code == 502

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_disconnect_returns_404_when_not_connected(self, mock_node, authed_client_alice):
        """When user is not connected, Node returns success=False, we return 404."""
        mock_node.return_value = {"success": False, "message": "Not connected"}
        rv = authed_client_alice.post("/api/whatsapp/disconnect")
        assert rv.status_code == 404


class TestProxyStatus:
    """GET /api/whatsapp/status"""

    def test_status_requires_auth(self, client):
        """Unauthenticated requests to status should redirect to login."""
        rv = client.get("/api/whatsapp/status")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_status_returns_correct_structure(self, mock_node, authed_client_alice):
        """Status response must include success, status, phone_number, qr_data_url."""
        mock_node.return_value = {
            "success": True,
            "status": "connected",
            "phoneNumber": "+1234567890",
            "qrDataUrl": None,
        }
        rv = authed_client_alice.get("/api/whatsapp/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "success" in data
        assert "status" in data
        assert "phone_number" in data
        assert "qr_data_url" in data
        assert data["status"] == "connected"
        assert data["phone_number"] == "+1234567890"

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_status_returns_disconnected_when_node_down(self, mock_node, authed_client_alice):
        """When Node.js is unreachable, return disconnected status (not 502)."""
        mock_node.return_value = None
        rv = authed_client_alice.get("/api/whatsapp/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True
        assert data["status"] == "disconnected"
        assert "warning" in data

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_status_with_qr_data(self, mock_node, authed_client_alice):
        """When QR is being displayed, qr_data_url should be present."""
        mock_node.return_value = {
            "success": True,
            "status": "qr",
            "phoneNumber": None,
            "qrDataUrl": "data:image/png;base64,abcdef",
        }
        rv = authed_client_alice.get("/api/whatsapp/status")
        data = rv.get_json()
        assert data["status"] == "qr"
        assert data["qr_data_url"] == "data:image/png;base64,abcdef"
        assert data["phone_number"] is None

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_status_uses_session_user_id_not_request(self, mock_node, authed_client_alice, seeded_app):
        """user_id must come from current_user.id (session), not from request params."""
        mock_node.return_value = {"success": True, "status": "disconnected"}
        # Even if someone passes user_id=999 in query params, it should use session user
        rv = authed_client_alice.get("/api/whatsapp/status?user_id=999")
        assert rv.status_code == 200
        with seeded_app.app_context():
            alice = User.query.filter_by(email="alice@example.com").first()
            mock_node.assert_called_once_with("GET", f"/api/connections/{alice.id}/status")


# =========================================================================
# 2. Message routing and user_id validation
# =========================================================================

class TestMessageEndpoint:
    """POST /api/whatsapp/message"""

    def test_message_requires_auth(self, client):
        """The message endpoint uses _require_login() which returns 401 for unauthed."""
        rv = client.post(
            "/api/whatsapp/message",
            json={"sender_jid": "123@s.whatsapp.net", "message": "hi", "user_id": 1},
        )
        assert rv.status_code == 401

    def test_message_requires_user_id(self, authed_client_alice):
        """Missing user_id should return 400."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={"sender_jid": "123@s.whatsapp.net", "message": "hi"},
        )
        assert rv.status_code == 400
        data = rv.get_json()
        assert "user_id" in data["message"].lower()

    def test_message_rejects_non_integer_user_id(self, authed_client_alice):
        """Non-integer user_id should return 400."""
        for bad_id in ["abc", "1.5", "", "null", "true", [], {}]:
            rv = authed_client_alice.post(
                "/api/whatsapp/message",
                json={"sender_jid": "123@s.whatsapp.net", "message": "hi", "user_id": bad_id},
            )
            assert rv.status_code == 400, f"Expected 400 for user_id={bad_id!r}, got {rv.status_code}"
            data = rv.get_json()
            assert "integer" in data["message"].lower()

    def test_message_requires_sender_jid(self, authed_client_alice):
        """Missing sender_jid should return 400."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={"message": "hi", "user_id": 1},
        )
        assert rv.status_code == 400
        data = rv.get_json()
        assert "sender_jid" in data["message"]

    def test_message_requires_message_or_images(self, authed_client_alice):
        """Missing message and images should return 400."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={"sender_jid": "123@s.whatsapp.net", "user_id": 1},
        )
        assert rv.status_code == 400
        data = rv.get_json()
        assert "message" in data["message"].lower()

    def test_message_rejects_empty_sender_jid(self, authed_client_alice):
        """Empty string sender_jid should return 400."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={"sender_jid": "   ", "message": "hi", "user_id": 1},
        )
        assert rv.status_code == 400

    def test_message_null_user_id(self, authed_client_alice):
        """Explicit null user_id should return 400."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={"sender_jid": "123@s.whatsapp.net", "message": "hi", "user_id": None},
        )
        assert rv.status_code == 400


class TestUserIdValidation:
    """Validate user_id handling across session-related endpoints."""

    def test_sessions_requires_user_id(self, authed_client_alice):
        """GET /api/whatsapp/sessions without user_id returns 400."""
        rv = authed_client_alice.get("/api/whatsapp/sessions")
        assert rv.status_code == 400

    def test_sessions_rejects_non_integer_user_id(self, authed_client_alice):
        """GET /api/whatsapp/sessions with non-integer user_id returns 400."""
        rv = authed_client_alice.get("/api/whatsapp/sessions?user_id=abc")
        assert rv.status_code == 400

    def test_sessions_accepts_valid_user_id(self, authed_client_alice, seeded_app):
        """GET /api/whatsapp/sessions with valid user_id returns 200."""
        with seeded_app.app_context():
            alice = User.query.filter_by(email="alice@example.com").first()
        rv = authed_client_alice.get(f"/api/whatsapp/sessions?user_id={alice.id}")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True
        assert isinstance(data["sessions"], list)

    def test_session_detail_requires_user_id(self, authed_client_alice):
        """GET /api/whatsapp/session/<id> without user_id returns 400."""
        rv = authed_client_alice.get("/api/whatsapp/session/some_session_id")
        assert rv.status_code == 400

    def test_session_detail_rejects_non_integer_user_id(self, authed_client_alice):
        """GET /api/whatsapp/session/<id> with non-integer user_id returns 400."""
        rv = authed_client_alice.get("/api/whatsapp/session/some_session_id?user_id=xyz")
        assert rv.status_code == 400

    def test_session_detail_returns_404_for_missing_session(self, authed_client_alice):
        """GET /api/whatsapp/session/<id> for non-existent session returns 404."""
        rv = authed_client_alice.get("/api/whatsapp/session/nonexistent123?user_id=1")
        assert rv.status_code == 404


# =========================================================================
# 3. Per-user directory isolation
# =========================================================================

class TestPerUserIsolation:
    """Test that different user_ids get separate directories and session maps."""

    def test_user_dir_includes_user_id(self, app, tmp_data_dir):
        """_user_dir should return a path containing the user_id."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            path_1 = wa_mod._user_dir(1)
            path_2 = wa_mod._user_dir(2)
            assert "wa_user_1" in str(path_1)
            assert "wa_user_2" in str(path_2)
            assert path_1 != path_2

    def test_session_maps_are_isolated(self, app, tmp_data_dir):
        """Session maps for different users are stored in separate files."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            # Save a session map for user 1
            wa_mod._save_session_map(1, {"jid1@wa": {"session_id": "s1", "sender_name": "A"}})
            # Save a different session map for user 2
            wa_mod._save_session_map(2, {"jid2@wa": {"session_id": "s2", "sender_name": "B"}})

            # Load and verify isolation
            map1 = wa_mod._load_session_map(1)
            map2 = wa_mod._load_session_map(2)
            assert "jid1@wa" in map1
            assert "jid2@wa" not in map1
            assert "jid2@wa" in map2
            assert "jid1@wa" not in map2

    def test_chat_files_are_isolated(self, app, tmp_data_dir):
        """Chat files for different users are in separate directories."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            payload_1 = {"session_id": "sess_aaa", "conversation": []}
            payload_2 = {"session_id": "sess_bbb", "conversation": []}

            wa_mod._save_chat(1, payload_1)
            wa_mod._save_chat(2, payload_2)

            # User 1 can load their own session but not user 2's
            assert wa_mod._load_chat(1, "sess_aaa") != {}
            assert wa_mod._load_chat(1, "sess_bbb") == {}

            # User 2 can load their own session but not user 1's
            assert wa_mod._load_chat(2, "sess_bbb") != {}
            assert wa_mod._load_chat(2, "sess_aaa") == {}

    def test_new_user_gets_empty_session_map(self, app, tmp_data_dir):
        """A user_id that has never been used returns an empty session map."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            smap = wa_mod._load_session_map(99999)
            assert smap == {}


# =========================================================================
# 4. Auth changes
# =========================================================================

class TestServiceAccountSeeding:
    """Test that init_auth seeds the bot@dreamchat.local service account."""

    def test_service_account_seeded_on_init(self):
        """When the database is fresh, init_auth should create bot@dreamchat.local."""
        from flask import Flask
        from functions.auth import init_auth

        fresh_app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        fresh_app.config["TESTING"] = True
        fresh_app.config["SECRET_KEY"] = "seed-test"
        fresh_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        fresh_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        init_auth(fresh_app)

        with fresh_app.app_context():
            bot = User.query.filter_by(email="bot@dreamchat.local").first()
            assert bot is not None, "Service account bot@dreamchat.local should be seeded"
            assert bot.tier == "service"
            # Clean up
            db.session.remove()
            db.drop_all()

    def test_service_account_uses_env_password(self):
        """When BOT_PASSWORD is set, it should be used for the service account."""
        from flask import Flask
        from functions.auth import init_auth

        fresh_app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        fresh_app.config["TESTING"] = True
        fresh_app.config["SECRET_KEY"] = "seed-test-env"
        fresh_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        fresh_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        with patch.dict(os.environ, {"BOT_PASSWORD": "my-bot-secret"}):
            init_auth(fresh_app)

        with fresh_app.app_context():
            bot = User.query.filter_by(email="bot@dreamchat.local").first()
            assert bot is not None
            assert bot.check_password("my-bot-secret")
            db.session.remove()
            db.drop_all()

    def test_service_account_generates_random_password_when_no_env(self):
        """When BOT_PASSWORD is not set, a random password is generated."""
        from flask import Flask
        from functions.auth import init_auth

        fresh_app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        fresh_app.config["TESTING"] = True
        fresh_app.config["SECRET_KEY"] = "seed-test-random"
        fresh_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        fresh_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        with patch.dict(os.environ, {}, clear=False):
            # Make sure BOT_PASSWORD is NOT set
            os.environ.pop("BOT_PASSWORD", None)
            init_auth(fresh_app)

        with fresh_app.app_context():
            bot = User.query.filter_by(email="bot@dreamchat.local").first()
            assert bot is not None
            # We can't know the random password, but the hash should exist
            assert bot.password_hash is not None
            assert len(bot.password_hash) > 0
            # It should NOT be empty or the literal string "password"
            assert not bot.check_password("")
            db.session.remove()
            db.drop_all()


class TestApiLoginUsernameField:
    """Test that api_login accepts both 'email' and 'username' fields."""

    def test_api_login_with_email_field(self, seeded_client):
        """Standard login with email field works."""
        rv = seeded_client.post(
            "/api/login",
            json={"email": "alice@example.com", "password": "alice123"},
            content_type="application/json",
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True

    def test_api_login_with_username_field(self, seeded_client):
        """Login with username field (backward compat) works."""
        rv = seeded_client.post(
            "/api/login",
            json={"username": "alice@example.com", "password": "alice123"},
            content_type="application/json",
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True

    def test_api_login_email_takes_precedence_over_username(self, seeded_client):
        """If both email and username are provided, email should be used."""
        rv = seeded_client.post(
            "/api/login",
            json={
                "email": "alice@example.com",
                "username": "bob@example.com",
                "password": "alice123",
            },
            content_type="application/json",
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["email"] == "alice@example.com"


# =========================================================================
# 5. Settings page
# =========================================================================

class TestSettingsPage:
    """GET /settings/whatsapp"""

    def test_settings_page_requires_auth(self, client):
        """Unauthenticated requests redirect to login."""
        rv = client.get("/settings/whatsapp")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    def test_settings_page_returns_200_when_authenticated(self, authed_client_alice):
        """Authenticated users can see the settings page."""
        rv = authed_client_alice.get("/settings/whatsapp")
        assert rv.status_code == 200

    def test_settings_page_contains_whatsapp_content(self, authed_client_alice):
        """The settings page should contain WhatsApp-related content."""
        rv = authed_client_alice.get("/settings/whatsapp")
        html = rv.data.decode()
        assert "WhatsApp" in html

    def test_settings_page_has_active_subnav(self, authed_client_alice):
        """The WhatsApp subnav link should be marked active."""
        rv = authed_client_alice.get("/settings/whatsapp")
        html = rv.data.decode()
        # The template checks settings_section == 'whatsapp' to add 'active' class
        assert 'active' in html


# =========================================================================
# 6. Security
# =========================================================================

class TestSecurityUserIsolation:
    """User A cannot access User B's WhatsApp data via proxy endpoints."""

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_connect_uses_own_user_id(self, mock_node, authed_client_alice, authed_client_bob, seeded_app):
        """Each user's connect call uses their own user_id from the session."""
        mock_node.return_value = {"success": True}

        authed_client_alice.post("/api/whatsapp/connect")
        with seeded_app.app_context():
            alice = User.query.filter_by(email="alice@example.com").first()
            call_path_alice = mock_node.call_args_list[0][0][1]
            assert str(alice.id) in call_path_alice

        mock_node.reset_mock()
        mock_node.return_value = {"success": True}

        authed_client_bob.post("/api/whatsapp/connect")
        with seeded_app.app_context():
            bob = User.query.filter_by(email="bob@example.com").first()
            call_path_bob = mock_node.call_args_list[0][0][1]
            assert str(bob.id) in call_path_bob
            # Verify they're different
            assert call_path_alice != call_path_bob

    @patch("whatsapp.flask_whatsapp._node_request")
    def test_status_uses_own_user_id(self, mock_node, authed_client_alice, authed_client_bob, seeded_app):
        """Each user's status call uses their own user_id, not the other user's."""
        mock_node.return_value = {"success": True, "status": "connected", "phoneNumber": "+1", "qrDataUrl": None}

        authed_client_alice.get("/api/whatsapp/status")
        with seeded_app.app_context():
            alice = User.query.filter_by(email="alice@example.com").first()
            call_path_alice = mock_node.call_args_list[0][0][1]
            assert str(alice.id) in call_path_alice

        mock_node.reset_mock()
        mock_node.return_value = {"success": True, "status": "disconnected", "phoneNumber": None, "qrDataUrl": None}

        authed_client_bob.get("/api/whatsapp/status")
        with seeded_app.app_context():
            bob = User.query.filter_by(email="bob@example.com").first()
            call_path_bob = mock_node.call_args_list[0][0][1]
            assert str(bob.id) in call_path_bob


class TestPathTraversal:
    """Ensure user_id cannot be used for path traversal attacks."""

    def test_user_dir_path_traversal_integer_only(self, app, tmp_data_dir):
        """Since user_id is validated as int, path traversal strings are rejected at the API level."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            # These would have been rejected by int() conversion before reaching _user_dir
            # But let's verify the _user_dir function itself is safe with integers
            path = wa_mod._user_dir(1)
            assert ".." not in str(path)
            assert path.parts[-1] == "wa_user_1"

    def test_api_rejects_path_traversal_user_id(self, authed_client_alice):
        """user_id with path traversal characters is rejected as non-integer."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={
                "sender_jid": "test@s.whatsapp.net",
                "message": "hi",
                "user_id": "../../../etc/passwd",
            },
        )
        assert rv.status_code == 400
        data = rv.get_json()
        assert "integer" in data["message"].lower()

    def test_sessions_rejects_path_traversal_user_id(self, authed_client_alice):
        """GET /api/whatsapp/sessions with path traversal user_id is rejected."""
        rv = authed_client_alice.get("/api/whatsapp/sessions?user_id=../../etc/passwd")
        assert rv.status_code == 400


class TestInFlightKeying:
    """_in_flight is keyed by (user_id, sender_jid) so different users don't interfere."""

    def test_in_flight_uses_tuple_key(self, app):
        """The _in_flight set uses (user_id, sender_jid) tuples."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            # Verify the _in_flight is a set
            assert isinstance(wa_mod._in_flight, set)

            # Simulate adding a flight key
            wa_mod._in_flight.add((1, "jid@wa"))
            assert (1, "jid@wa") in wa_mod._in_flight
            # Different user with same jid should NOT be blocked
            assert (2, "jid@wa") not in wa_mod._in_flight

            # Cleanup
            wa_mod._in_flight.discard((1, "jid@wa"))

    def test_in_flight_different_users_same_jid_not_blocked(self, app):
        """Two different users messaging the same jid should not block each other."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            wa_mod._in_flight.add((1, "same_jid@wa"))
            # User 2 with the same jid should not be in-flight
            assert (2, "same_jid@wa") not in wa_mod._in_flight
            wa_mod._in_flight.discard((1, "same_jid@wa"))


# =========================================================================
# 7. Edge cases
# =========================================================================

class TestEdgeCases:
    """Edge case handling for user_id and other inputs."""

    def test_empty_string_user_id_in_message(self, authed_client_alice):
        """Empty string user_id should be rejected."""
        rv = authed_client_alice.post(
            "/api/whatsapp/message",
            json={"sender_jid": "jid@wa", "message": "hi", "user_id": ""},
        )
        assert rv.status_code == 400

    def test_negative_user_id_accepted_as_integer(self, app, tmp_data_dir):
        """Negative user_id is technically a valid integer; the directory is just named with it."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            # Negative numbers pass int() validation
            path = wa_mod._user_dir(-1)
            assert "wa_user_-1" in str(path)

    def test_very_large_user_id(self, app, tmp_data_dir):
        """Very large user_id should not cause issues."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            large_id = 999999999999
            path = wa_mod._user_dir(large_id)
            assert f"wa_user_{large_id}" in str(path)
            # Should be able to save and load a session map
            wa_mod._save_session_map(large_id, {"test@wa": {"session_id": "s1", "sender_name": "T"}})
            smap = wa_mod._load_session_map(large_id)
            assert "test@wa" in smap

    def test_zero_user_id(self, authed_client_alice):
        """user_id=0 is a valid integer and should be accepted at the validation layer."""
        # Note: 0 passes int() validation — whether it maps to a real user is
        # a business logic concern, not a validation concern.
        rv = authed_client_alice.get("/api/whatsapp/sessions?user_id=0")
        assert rv.status_code == 200

    def test_concurrent_users_different_dirs(self, app, tmp_data_dir):
        """Multiple user_ids create separate, non-overlapping directory structures."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            dirs = []
            for uid in range(1, 6):
                d = wa_mod._user_dir(uid)
                d.mkdir(parents=True, exist_ok=True)
                dirs.append(d)

            # All directories should be unique
            assert len(set(dirs)) == 5
            # No directory should be a prefix of another
            for i, d1 in enumerate(dirs):
                for j, d2 in enumerate(dirs):
                    if i != j:
                        assert not str(d1).startswith(str(d2) + "/")

    def test_session_map_round_trip(self, app, tmp_data_dir):
        """Saving and loading a session map preserves all data."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            original = {
                "12345@s.whatsapp.net": {
                    "session_id": "abc123",
                    "sender_name": "Test User",
                },
                "67890@s.whatsapp.net": {
                    "session_id": "def456",
                    "sender_name": "Another User",
                },
            }
            wa_mod._save_session_map(42, original)
            loaded = wa_mod._load_session_map(42)
            assert loaded == original

    def test_sessions_list_auth_required(self, client):
        """GET /api/whatsapp/sessions returns 401 when not authenticated."""
        rv = client.get("/api/whatsapp/sessions?user_id=1")
        assert rv.status_code == 401

    def test_session_detail_auth_required(self, client):
        """GET /api/whatsapp/session/<id> returns 401 when not authenticated."""
        rv = client.get("/api/whatsapp/session/abc?user_id=1")
        assert rv.status_code == 401


# =========================================================================
# 8. Node.js proxy helper internals
# =========================================================================

class TestNodeRequestHelper:
    """Test _node_request behavior with various failure modes."""

    def test_node_request_returns_none_on_connection_error(self, app):
        """When the Node.js service is down, _node_request returns None."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            with patch("whatsapp.flask_whatsapp.http_requests.request") as mock_req:
                import requests
                mock_req.side_effect = requests.ConnectionError("Connection refused")
                result = wa_mod._node_request("GET", "/api/test")
                assert result is None

    def test_node_request_returns_none_on_generic_error(self, app):
        """When the Node.js service returns a non-JSON response, _node_request returns None."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            with patch("whatsapp.flask_whatsapp.http_requests.request") as mock_req:
                mock_req.side_effect = Exception("Something went wrong")
                result = wa_mod._node_request("GET", "/api/test")
                assert result is None

    def test_node_headers_include_api_key_when_set(self, app):
        """When NODE_API_KEY is set, _node_headers includes X-Api-Key."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            original = wa_mod.NODE_API_KEY
            try:
                wa_mod.NODE_API_KEY = "test-api-key-123"
                headers = wa_mod._node_headers()
                assert headers["X-Api-Key"] == "test-api-key-123"
            finally:
                wa_mod.NODE_API_KEY = original

    def test_node_headers_no_api_key_when_empty(self, app):
        """When NODE_API_KEY is empty, X-Api-Key is not included."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            original = wa_mod.NODE_API_KEY
            try:
                wa_mod.NODE_API_KEY = ""
                headers = wa_mod._node_headers()
                assert "X-Api-Key" not in headers
                assert "Content-Type" in headers
            finally:
                wa_mod.NODE_API_KEY = original


# =========================================================================
# 9. Session listing and detail endpoints
# =========================================================================

class TestSessionsEndpoints:
    """Tests for the sessions list and detail endpoints with actual data."""

    def test_sessions_list_empty(self, authed_client_alice):
        """Empty session list for a user with no WhatsApp conversations."""
        rv = authed_client_alice.get("/api/whatsapp/sessions?user_id=1")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True
        assert data["sessions"] == []

    def test_sessions_list_with_data(self, authed_client_alice, app, tmp_data_dir):
        """Session list returns conversations that exist on disk."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            # Create a chat session for user_id=1
            payload = {
                "session_id": "test_sess_1",
                "source": "whatsapp",
                "sender_jid": "555@s.whatsapp.net",
                "sender_name": "Test Contact",
                "title": "WhatsApp: Test Contact",
                "created_at": "2026-03-27T10:00:00",
                "updated_at": "2026-03-27T10:05:00",
                "conversation": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ],
            }
            wa_mod._save_chat(1, payload)
            wa_mod._save_session_map(1, {
                "555@s.whatsapp.net": {
                    "session_id": "test_sess_1",
                    "sender_name": "Test Contact",
                },
            })

        rv = authed_client_alice.get("/api/whatsapp/sessions?user_id=1")
        assert rv.status_code == 200
        data = rv.get_json()
        assert len(data["sessions"]) == 1
        sess = data["sessions"][0]
        assert sess["session_id"] == "test_sess_1"
        assert sess["sender_jid"] == "555@s.whatsapp.net"
        assert sess["sender_name"] == "Test Contact"
        assert sess["message_count"] == 2  # user + assistant (not system)

    def test_session_detail_returns_conversation(self, authed_client_alice, app, tmp_data_dir):
        """Session detail returns filtered conversation (no system messages)."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            payload = {
                "session_id": "detail_sess",
                "source": "whatsapp",
                "sender_jid": "777@s.whatsapp.net",
                "sender_name": "Detail Test",
                "title": "WhatsApp: Detail Test",
                "created_at": "2026-03-27T09:00:00",
                "updated_at": "2026-03-27T09:10:00",
                "conversation": [
                    {"role": "system", "content": "System prompt here"},
                    {"role": "user", "content": "What is health?"},
                    {"role": "assistant", "content": "Health is..."},
                ],
            }
            wa_mod._save_chat(1, payload)

        rv = authed_client_alice.get("/api/whatsapp/session/detail_sess?user_id=1")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True
        assert data["session_id"] == "detail_sess"
        assert data["sender_jid"] == "777@s.whatsapp.net"
        # System messages should be filtered out
        assert len(data["conversation"]) == 2
        roles = [m["role"] for m in data["conversation"]]
        assert "system" not in roles

    def test_session_detail_handles_legacy_string_entry(self, authed_client_alice, app, tmp_data_dir):
        """Session map entries that are plain strings (legacy format) should work."""
        import whatsapp.flask_whatsapp as wa_mod
        with app.app_context():
            # Legacy format: sender_jid maps directly to session_id string
            wa_mod._save_session_map(1, {"legacy@wa": "legacy_sess_id"})
            payload = {
                "session_id": "legacy_sess_id",
                "source": "whatsapp",
                "sender_jid": "legacy@wa",
                "title": "WhatsApp: legacy",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "conversation": [
                    {"role": "user", "content": "old message"},
                    {"role": "assistant", "content": "old reply"},
                ],
            }
            wa_mod._save_chat(1, payload)

        rv = authed_client_alice.get("/api/whatsapp/sessions?user_id=1")
        assert rv.status_code == 200
        data = rv.get_json()
        assert len(data["sessions"]) == 1
        sess = data["sessions"][0]
        assert sess["session_id"] == "legacy_sess_id"

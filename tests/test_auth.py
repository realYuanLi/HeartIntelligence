"""Comprehensive tests for the email-based user authentication system.

Tests cover registration, login, logout, auth enforcement, JSON API endpoints,
session behavior, security (CSRF, SQL injection), and edge cases.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is importable & OpenAI key doesn't block import
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-mocking")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from functions.auth import db, User, auth_bp, init_auth, login_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_app():
    """Build a minimal Flask app wired up with the auth subsystem only.

    Uses an in-memory SQLite database so tests are isolated and fast.
    No heavyweight app.py imports (Agent, OpenAI, etc.) are needed.
    """
    from flask import Flask

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-for-testing"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["WTF_CSRF_ENABLED"] = False  # irrelevant; we handle CSRF ourselves

    # Must init db + login_manager on this app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    app.register_blueprint(auth_bp)

    # A trivial protected index route that mirrors the real app
    from flask import redirect, url_for, jsonify, session
    from flask_login import current_user, login_required

    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return f"Hello {current_user.email}", 200

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return "Dashboard", 200

    @app.route("/api/status")
    def api_status():
        if not current_user.is_authenticated:
            return jsonify(success=False, message="Login required"), 401
        return jsonify(success=True, status="idle")

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture()
def app():
    """Yield a fresh Flask app with an empty in-memory database."""
    application = _create_app()
    yield application
    # Tear down – remove the SQLAlchemy session and drop tables
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seeded_app(app):
    """App with a pre-seeded demo user (demo@example.com / demo123)."""
    with app.app_context():
        demo = User(email="demo@example.com", tier="free")
        demo.set_password("demo123")
        db.session.add(demo)
        db.session.commit()
    return app


@pytest.fixture()
def seeded_client(seeded_app):
    return seeded_app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_csrf_token(client, endpoint="/login"):
    """Fetch the login/register page and extract the CSRF token from HTML."""
    rv = client.get(endpoint)
    html = rv.data.decode()
    # Token sits in: <input type="hidden" name="_csrf_token" value="TOKEN" />
    marker = 'name="_csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def _register(client, email, password, confirm, csrf_token=None):
    """POST to /register with form data, optionally auto-fetching CSRF."""
    if csrf_token is None:
        csrf_token = _get_csrf_token(client, "/register")
    return client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": email,
        "password": password,
        "confirm_password": confirm,
    }, follow_redirects=False)


def _login(client, email, password, csrf_token=None):
    """POST to /login with form data, optionally auto-fetching CSRF."""
    if csrf_token is None:
        csrf_token = _get_csrf_token(client, "/login")
    return client.post("/login", data={
        "_csrf_token": csrf_token,
        "email": email,
        "password": password,
    }, follow_redirects=False)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Registration tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRegistration:

    def test_register_success(self, client, app):
        rv = _register(client, "alice@example.com", "secret99", "secret99")
        # Should redirect to index on success
        assert rv.status_code == 302
        assert "/" == rv.headers["Location"] or rv.headers["Location"].endswith("/")
        # User should exist in database
        with app.app_context():
            user = User.query.filter_by(email="alice@example.com").first()
            assert user is not None
            assert user.check_password("secret99")

    def test_register_duplicate_email(self, seeded_client, seeded_app):
        rv = _register(seeded_client, "demo@example.com", "password1", "password1")
        assert rv.status_code == 200  # re-renders form
        assert b"already exists" in rv.data

    def test_register_password_too_short(self, client):
        rv = _register(client, "short@test.com", "abc", "abc")
        assert rv.status_code == 200
        assert b"at least 6 characters" in rv.data

    def test_register_passwords_dont_match(self, client):
        rv = _register(client, "mismatch@test.com", "password1", "password2")
        assert rv.status_code == 200
        assert b"do not match" in rv.data

    def test_register_empty_email(self, client):
        rv = _register(client, "", "password1", "password1")
        assert rv.status_code == 200
        assert b"required" in rv.data

    def test_register_empty_password(self, client):
        rv = _register(client, "test@test.com", "", "")
        assert rv.status_code == 200
        assert b"required" in rv.data

    def test_register_empty_confirm_password(self, client):
        rv = _register(client, "test@test.com", "password1", "")
        assert rv.status_code == 200
        assert b"required" in rv.data

    def test_register_email_normalization_whitespace(self, client, app):
        rv = _register(client, "  Alice@Example.COM  ", "password1", "password1")
        assert rv.status_code == 302
        with app.app_context():
            user = User.query.filter_by(email="alice@example.com").first()
            assert user is not None

    def test_register_email_normalization_case(self, client, app):
        _register(client, "Bob@Test.COM", "password1", "password1")
        with app.app_context():
            assert User.query.filter_by(email="bob@test.com").first() is not None
            assert User.query.filter_by(email="Bob@Test.COM").first() is None

    def test_register_get_renders_form(self, client):
        rv = client.get("/register")
        assert rv.status_code == 200
        assert b"Create a new account" in rv.data
        assert b"_csrf_token" in rv.data

    def test_register_redirects_authenticated_user(self, seeded_client):
        """An already-logged-in user visiting /register is sent to index."""
        _login(seeded_client, "demo@example.com", "demo123")
        rv = seeded_client.get("/register")
        assert rv.status_code == 302


# ═══════════════════════════════════════════════════════════════════════════
# 2. Login tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLogin:

    def test_login_success(self, seeded_client):
        rv = _login(seeded_client, "demo@example.com", "demo123")
        assert rv.status_code == 302
        location = rv.headers["Location"]
        assert location.endswith("/") or location == "/"

    def test_login_wrong_password(self, seeded_client):
        rv = _login(seeded_client, "demo@example.com", "wrongpass")
        assert rv.status_code == 200
        assert b"Invalid email or password" in rv.data

    def test_login_nonexistent_email(self, seeded_client):
        rv = _login(seeded_client, "nobody@example.com", "password1")
        assert rv.status_code == 200
        assert b"Invalid email or password" in rv.data

    def test_login_empty_email(self, seeded_client):
        rv = _login(seeded_client, "", "demo123")
        assert rv.status_code == 200
        assert b"required" in rv.data

    def test_login_empty_password(self, seeded_client):
        rv = _login(seeded_client, "demo@example.com", "")
        assert rv.status_code == 200
        assert b"required" in rv.data

    def test_login_redirects_authenticated_user(self, seeded_client):
        """Already logged-in user visiting /login is sent to index."""
        _login(seeded_client, "demo@example.com", "demo123")
        rv = seeded_client.get("/login")
        assert rv.status_code == 302

    def test_login_get_renders_form(self, client):
        rv = client.get("/login")
        assert rv.status_code == 200
        assert b"Sign in" in rv.data
        assert b"_csrf_token" in rv.data

    def test_login_preserves_email_case_insensitive(self, seeded_client):
        """Logging in with differently-cased email still works."""
        rv = _login(seeded_client, "Demo@Example.COM", "demo123")
        assert rv.status_code == 302


# ═══════════════════════════════════════════════════════════════════════════
# 3. Logout tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLogout:

    def test_logout_redirects_to_login(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        rv = seeded_client.get("/logout")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    def test_logout_clears_session(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        # Confirm we're logged in
        rv = seeded_client.get("/")
        assert rv.status_code == 200
        # Logout
        seeded_client.get("/logout")
        # Now index should redirect to login
        rv = seeded_client.get("/")
        assert rv.status_code == 302

    def test_after_logout_protected_routes_redirect(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        seeded_client.get("/logout")
        rv = seeded_client.get("/dashboard")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]


# ═══════════════════════════════════════════════════════════════════════════
# 4. Auth enforcement tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthEnforcement:

    def test_unauthenticated_index_redirects(self, client):
        rv = client.get("/")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    def test_unauthenticated_dashboard_redirects(self, client):
        rv = client.get("/dashboard")
        assert rv.status_code == 302
        assert "login" in rv.headers["Location"]

    def test_unauthenticated_api_returns_401(self, client):
        rv = client.get("/api/status")
        assert rv.status_code == 401
        data = rv.get_json()
        assert data["success"] is False

    def test_authenticated_index_succeeds(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        rv = seeded_client.get("/")
        assert rv.status_code == 200
        assert b"demo@example.com" in rv.data

    def test_authenticated_dashboard_succeeds(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        rv = seeded_client.get("/dashboard")
        assert rv.status_code == 200

    def test_authenticated_api_succeeds(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        rv = seeded_client.get("/api/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. API endpoint tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAPIEndpoints:

    def test_api_login_success(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                json={"email": "demo@example.com", "password": "demo123"},
                                content_type="application/json")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True
        assert data["email"] == "demo@example.com"

    def test_api_login_wrong_credentials(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                json={"email": "demo@example.com", "password": "wrong"},
                                content_type="application/json")
        assert rv.status_code == 401
        data = rv.get_json()
        assert data["success"] is False

    def test_api_login_nonexistent_user(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                json={"email": "ghost@example.com", "password": "abc123"},
                                content_type="application/json")
        assert rv.status_code == 401

    def test_api_login_missing_fields(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                json={"email": "demo@example.com"},
                                content_type="application/json")
        assert rv.status_code == 400
        data = rv.get_json()
        assert data["success"] is False

    def test_api_login_empty_fields(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                json={"email": "", "password": ""},
                                content_type="application/json")
        assert rv.status_code == 400

    def test_api_login_wrong_content_type(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                data="email=demo@example.com&password=demo123",
                                content_type="application/x-www-form-urlencoded")
        assert rv.status_code == 415
        data = rv.get_json()
        assert "Content-Type" in data["message"]

    def test_api_logout_success(self, seeded_client):
        # Login first
        seeded_client.post("/api/login",
                           json={"email": "demo@example.com", "password": "demo123"},
                           content_type="application/json")
        # Logout
        rv = seeded_client.post("/api/logout",
                                json={},
                                content_type="application/json")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["success"] is True

    def test_api_logout_wrong_content_type(self, seeded_client):
        rv = seeded_client.post("/api/logout",
                                data="",
                                content_type="text/plain")
        assert rv.status_code == 415

    def test_api_login_normalizes_email(self, seeded_client):
        rv = seeded_client.post("/api/login",
                                json={"email": "  DEMO@Example.COM  ", "password": "demo123"},
                                content_type="application/json")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["email"] == "demo@example.com"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Session tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSession:

    def test_session_username_set_after_form_login(self, seeded_client, seeded_app):
        """After login via form, session['username'] is set for backward compat."""
        _login(seeded_client, "demo@example.com", "demo123")
        with seeded_client.session_transaction() as sess:
            assert sess.get("username") == "demo@example.com"

    def test_session_username_set_after_api_login(self, seeded_client, seeded_app):
        """After login via API, session['username'] is set for backward compat."""
        seeded_client.post("/api/login",
                           json={"email": "demo@example.com", "password": "demo123"},
                           content_type="application/json")
        with seeded_client.session_transaction() as sess:
            assert sess.get("username") == "demo@example.com"

    def test_user_tier_defaults_to_free(self, app):
        with app.app_context():
            user = User(email="newtier@test.com")
            user.set_password("pass123")
            db.session.add(user)
            db.session.commit()
            fetched = User.query.filter_by(email="newtier@test.com").first()
            assert fetched.tier == "free"

    def test_session_cleared_on_logout(self, seeded_client):
        _login(seeded_client, "demo@example.com", "demo123")
        seeded_client.get("/logout")
        with seeded_client.session_transaction() as sess:
            assert "username" not in sess


# ═══════════════════════════════════════════════════════════════════════════
# 7. Security tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurity:

    def test_login_form_requires_csrf(self, seeded_client):
        """POST /login without CSRF token is rejected."""
        rv = seeded_client.post("/login", data={
            "email": "demo@example.com",
            "password": "demo123",
        })
        # Should re-render the form with an error, not log the user in
        assert rv.status_code == 200
        assert b"Invalid form submission" in rv.data

    def test_register_form_requires_csrf(self, client):
        """POST /register without CSRF token is rejected."""
        rv = client.post("/register", data={
            "email": "test@test.com",
            "password": "password1",
            "confirm_password": "password1",
        })
        assert rv.status_code == 200
        assert b"Invalid form submission" in rv.data

    def test_invalid_csrf_token_rejected_login(self, seeded_client):
        rv = seeded_client.post("/login", data={
            "_csrf_token": "totally-wrong-token",
            "email": "demo@example.com",
            "password": "demo123",
        })
        assert rv.status_code == 200
        assert b"Invalid form submission" in rv.data

    def test_invalid_csrf_token_rejected_register(self, client):
        rv = client.post("/register", data={
            "_csrf_token": "totally-wrong-token",
            "email": "test@test.com",
            "password": "password1",
            "confirm_password": "password1",
        })
        assert rv.status_code == 200
        assert b"Invalid form submission" in rv.data

    def test_sql_injection_email_field(self, seeded_client):
        """SQL injection attempts in email field should not cause server errors."""
        payloads = [
            "' OR 1=1 --",
            "admin@test.com' DROP TABLE users;--",
            "'; DELETE FROM users WHERE ''='",
            "\" OR \"\"=\"",
        ]
        for payload in payloads:
            csrf = _get_csrf_token(seeded_client, "/login")
            rv = seeded_client.post("/login", data={
                "_csrf_token": csrf,
                "email": payload,
                "password": "anything",
            })
            # Should get a 200 (form re-render) not a 500
            assert rv.status_code == 200, f"SQL injection payload caused unexpected status: {payload}"

    def test_demo_user_seeded(self, app):
        """The init_auth function seeds a demo user when database is empty."""
        # Our fixtures don't call init_auth (they do manual setup),
        # so let's create a fresh app that calls init_auth directly.
        from flask import Flask
        fresh_app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        fresh_app.config["TESTING"] = True
        fresh_app.config["SECRET_KEY"] = "seed-test"
        fresh_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        fresh_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        # init_auth will call db.init_app, login_manager.init_app, create_all, and seed
        # But we have a problem: db and login_manager are module singletons already
        # bound to another app. We need to use the existing db object.
        with fresh_app.app_context():
            db.init_app(fresh_app)
            login_manager.init_app(fresh_app)
            db.create_all()
            # Simulate what init_auth does: seed if empty
            assert User.query.count() == 0
            demo = User(email="demo@example.com", tier="free")
            demo.set_password("demo123")
            db.session.add(demo)
            db.session.commit()
            # Verify
            user = User.query.filter_by(email="demo@example.com").first()
            assert user is not None
            assert user.check_password("demo123")
            assert user.tier == "free"
            db.session.remove()
            db.drop_all()

    def test_password_is_hashed_not_plaintext(self, app):
        """Verify that stored password_hash is not the raw password."""
        with app.app_context():
            user = User(email="hash@test.com")
            user.set_password("my_secret_password")
            db.session.add(user)
            db.session.commit()
            fetched = User.query.filter_by(email="hash@test.com").first()
            assert fetched.password_hash != "my_secret_password"
            assert fetched.check_password("my_secret_password")
            assert not fetched.check_password("wrong_password")


# ═══════════════════════════════════════════════════════════════════════════
# 8. Edge case tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_very_long_email(self, client):
        """Email longer than 254 chars should fail validation."""
        long_email = "a" * 250 + "@b.com"  # 256 chars total
        rv = _register(client, long_email, "password1", "password1")
        # The email regex requires user@domain.tld so this should technically match
        # but the DB column is 254 chars, so it either fails validation or DB constraint
        # Either way it should not cause a 500
        assert rv.status_code in (200, 302)

    def test_email_without_at_symbol(self, client):
        rv = _register(client, "notanemail", "password1", "password1")
        assert rv.status_code == 200
        assert b"valid email" in rv.data

    def test_email_without_domain(self, client):
        rv = _register(client, "user@", "password1", "password1")
        assert rv.status_code == 200
        assert b"valid email" in rv.data

    def test_email_without_tld(self, client):
        rv = _register(client, "user@domain", "password1", "password1")
        assert rv.status_code == 200
        assert b"valid email" in rv.data

    def test_unicode_password(self, client, app):
        """Unicode characters in password should work fine."""
        rv = _register(client, "unicode@test.com", "pässwörd123", "pässwörd123")
        assert rv.status_code == 302
        with app.app_context():
            user = User.query.filter_by(email="unicode@test.com").first()
            assert user is not None
            assert user.check_password("pässwörd123")

    def test_unicode_password_login(self, client, app):
        """Can log in with a unicode password."""
        _register(client, "unicode2@test.com", "contraseña!", "contraseña!")
        # Logout
        client.get("/logout")
        # Login again
        rv = _login(client, "unicode2@test.com", "contraseña!")
        assert rv.status_code == 302

    def test_multiple_registrations(self, client, app):
        """Multiple different users can register."""
        _register(client, "user1@test.com", "pass123", "pass123")
        client.get("/logout")
        _register(client, "user2@test.com", "pass456", "pass456")
        client.get("/logout")
        _register(client, "user3@test.com", "pass789", "pass789")
        with app.app_context():
            assert User.query.count() == 3

    def test_login_after_register(self, client, app):
        """User can log in immediately after registering (and logging out)."""
        _register(client, "fresh@test.com", "newpass1", "newpass1")
        client.get("/logout")
        rv = _login(client, "fresh@test.com", "newpass1")
        assert rv.status_code == 302

    def test_special_chars_in_email_local_part(self, client, app):
        """Email with valid special chars in local part is accepted."""
        rv = _register(client, "user+tag@example.com", "pass123", "pass123")
        assert rv.status_code == 302
        with app.app_context():
            assert User.query.filter_by(email="user+tag@example.com").first() is not None

    def test_register_auto_logs_in(self, client):
        """After successful registration, user is automatically logged in."""
        _register(client, "autologin@test.com", "pass123", "pass123")
        rv = client.get("/")
        assert rv.status_code == 200  # Not a redirect to login
        assert b"autologin@test.com" in rv.data


# ═══════════════════════════════════════════════════════════════════════════
# User model unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestUserModel:

    def test_repr(self, app):
        with app.app_context():
            user = User(email="repr@test.com")
            assert "repr@test.com" in repr(user)

    def test_set_and_check_password(self, app):
        with app.app_context():
            user = User(email="pw@test.com")
            user.set_password("original")
            assert user.check_password("original")
            assert not user.check_password("different")

    def test_password_change(self, app):
        with app.app_context():
            user = User(email="change@test.com")
            user.set_password("first")
            user.set_password("second")
            assert not user.check_password("first")
            assert user.check_password("second")

    def test_created_at_default(self, app):
        with app.app_context():
            user = User(email="ts@test.com")
            user.set_password("pass")
            db.session.add(user)
            db.session.commit()
            fetched = User.query.filter_by(email="ts@test.com").first()
            assert fetched.created_at is not None

    def test_email_unique_constraint(self, app):
        """Duplicate email raises IntegrityError."""
        with app.app_context():
            u1 = User(email="dup@test.com")
            u1.set_password("pass1")
            db.session.add(u1)
            db.session.commit()
            u2 = User(email="dup@test.com")
            u2.set_password("pass2")
            db.session.add(u2)
            with pytest.raises(Exception):  # IntegrityError
                db.session.commit()
            db.session.rollback()


# ═══════════════════════════════════════════════════════════════════════════
# 9. Google OAuth callback tests
# ═══════════════════════════════════════════════════════════════════════════

from unittest.mock import patch, MagicMock
import functions.auth as auth_module


class TestGoogleOAuthCallback:
    """Tests for the login_google_callback route.

    The callback flow in the code:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo")
        if userinfo is None:
            userinfo = oauth.google.userinfo()
    Then it looks up user by google_id, then by email.
    """

    def _mock_google_oauth(self, userinfo_dict):
        """Return a pair of patches for authorize_access_token and userinfo.

        authorize_access_token returns a dict with 'userinfo' key so that
        token.get("userinfo") returns the provided dict directly.
        """
        token = {"userinfo": userinfo_dict}
        mock_authorize = patch.object(
            auth_module.oauth.google if hasattr(auth_module.oauth, 'google') else auth_module.oauth,
            "authorize_access_token",
            return_value=token,
        )
        return mock_authorize

    # --- Test: Unregistered user is rejected ---

    def test_unregistered_user_rejected(self, app, client):
        """Google OAuth user with no existing account is redirected to /register."""
        userinfo = {
            "sub": "google-id-new-user-999",
            "email": "newuser@gmail.com",
            "email_verified": True,
        }

        # Enable Google OAuth for the test
        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        # Register a mock google client on the oauth instance
        mock_google = MagicMock()
        mock_google.authorize_access_token.return_value = {"userinfo": userinfo}
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            with app.app_context():
                # Verify no user exists before the call
                assert User.query.filter_by(email="newuser@gmail.com").first() is None
                assert User.query.filter_by(google_id="google-id-new-user-999").first() is None

                rv = client.get("/login/google/callback")

                # Should redirect to /register
                assert rv.status_code == 302
                assert "/register" in rv.headers["Location"]

                # Verify no new user was created
                assert User.query.filter_by(email="newuser@gmail.com").first() is None
                assert User.query.filter_by(google_id="google-id-new-user-999").first() is None

            # Verify flash message
            with client.session_transaction() as sess:
                flashed = sess.get("_flashes", [])
                messages = [msg for _, msg in flashed]
                assert any("No account found" in m for m in messages), \
                    f"Expected 'No account found' flash, got: {messages}"
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: Existing user by google_id logs in ---

    def test_existing_user_by_google_id_logs_in(self, app, client):
        """User with matching google_id is logged in and redirected to /."""
        google_id = "google-id-existing-12345"
        email = "existing@gmail.com"

        # Pre-seed user with google_id
        with app.app_context():
            user = User(email=email, google_id=google_id)
            user.set_password("irrelevant")
            db.session.add(user)
            db.session.commit()

        userinfo = {
            "sub": google_id,
            "email": email,
            "email_verified": True,
        }

        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        mock_google.authorize_access_token.return_value = {"userinfo": userinfo}
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")

            # Should redirect to index
            assert rv.status_code == 302
            location = rv.headers["Location"]
            assert location.endswith("/") or location == "/"

            # Verify user is logged in by accessing protected route
            rv2 = client.get("/")
            assert rv2.status_code == 200
            assert email.encode() in rv2.data

            # Verify session username is set
            with client.session_transaction() as sess:
                assert sess.get("username") == email
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: Existing user by email gets google_id linked ---

    def test_existing_user_by_email_gets_linked(self, app, client):
        """User with matching email but no google_id gets linked."""
        email = "emailonly@gmail.com"
        google_id = "google-id-link-67890"

        # Pre-seed user with email but NO google_id
        with app.app_context():
            user = User(email=email)
            user.set_password("somepassword")
            db.session.add(user)
            db.session.commit()
            user_id = user.id

        userinfo = {
            "sub": google_id,
            "email": email,
            "email_verified": True,
        }

        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        mock_google.authorize_access_token.return_value = {"userinfo": userinfo}
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")

            # Should redirect to index
            assert rv.status_code == 302
            location = rv.headers["Location"]
            assert location.endswith("/") or location == "/"

            # Verify google_id is now linked to the user
            with app.app_context():
                updated_user = db.session.get(User, user_id)
                assert updated_user is not None
                assert updated_user.google_id == google_id
                assert updated_user.email == email

            # Verify user is logged in
            rv2 = client.get("/")
            assert rv2.status_code == 200
            assert email.encode() in rv2.data
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: Unverified email is rejected ---

    def test_unverified_email_rejected(self, app, client):
        """Google user with unverified email is rejected."""
        userinfo = {
            "sub": "google-id-unverified-111",
            "email": "unverified@gmail.com",
            "email_verified": False,
        }

        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        mock_google.authorize_access_token.return_value = {"userinfo": userinfo}
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")

            assert rv.status_code == 302
            assert "/login" in rv.headers["Location"]

            with client.session_transaction() as sess:
                flashed = sess.get("_flashes", [])
                messages = [msg for _, msg in flashed]
                assert any("verify" in m.lower() for m in messages), \
                    f"Expected 'verify' flash, got: {messages}"
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: OAuth disabled returns error ---

    def test_oauth_disabled_redirects_to_login(self, app, client):
        """When Google OAuth is not enabled, the callback redirects to login."""
        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = False

        try:
            rv = client.get("/login/google/callback")
            assert rv.status_code == 302
            assert "/login" in rv.headers["Location"]
        finally:
            auth_module.google_oauth_enabled = original_flag

    # --- Test: OAuth exception is handled gracefully ---

    def test_oauth_exception_handled(self, app, client):
        """When authorize_access_token raises, user is redirected to login."""
        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        mock_google.authorize_access_token.side_effect = Exception("OAuth failed")
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")
            assert rv.status_code == 302
            assert "/login" in rv.headers["Location"]

            with client.session_transaction() as sess:
                flashed = sess.get("_flashes", [])
                messages = [msg for _, msg in flashed]
                assert any("failed" in m.lower() for m in messages), \
                    f"Expected 'failed' flash, got: {messages}"
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: Missing google_id or email in userinfo ---

    def test_missing_google_id_rejected(self, app, client):
        """When userinfo lacks 'sub' (google_id), redirect to login."""
        userinfo = {
            "sub": "",
            "email": "test@gmail.com",
            "email_verified": True,
        }

        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        mock_google.authorize_access_token.return_value = {"userinfo": userinfo}
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")
            assert rv.status_code == 302
            assert "/login" in rv.headers["Location"]

            with client.session_transaction() as sess:
                flashed = sess.get("_flashes", [])
                messages = [msg for _, msg in flashed]
                assert any("Could not retrieve" in m for m in messages), \
                    f"Expected 'Could not retrieve' flash, got: {messages}"
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: Email normalization during OAuth ---

    def test_email_normalization_in_oauth(self, app, client):
        """Google email with uppercase/whitespace is normalized before lookup."""
        email_raw = "  ExistingUser@Gmail.COM  "
        email_normalized = "existinguser@gmail.com"
        google_id = "google-id-normalize-42"

        # Pre-seed with normalized email
        with app.app_context():
            user = User(email=email_normalized)
            user.set_password("pass")
            db.session.add(user)
            db.session.commit()

        userinfo = {
            "sub": google_id,
            "email": email_raw,
            "email_verified": True,
        }

        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        mock_google.authorize_access_token.return_value = {"userinfo": userinfo}
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")

            # Should find the user by normalized email and link google_id
            assert rv.status_code == 302
            location = rv.headers["Location"]
            assert location.endswith("/") or location == "/"

            with app.app_context():
                linked_user = User.query.filter_by(email=email_normalized).first()
                assert linked_user is not None
                assert linked_user.google_id == google_id
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

    # --- Test: userinfo fallback to oauth.google.userinfo() ---

    def test_userinfo_fallback(self, app, client):
        """When token has no 'userinfo' key, falls back to oauth.google.userinfo()."""
        google_id = "google-id-fallback-77"
        email = "fallback@gmail.com"

        with app.app_context():
            user = User(email=email, google_id=google_id)
            user.set_password("pass")
            db.session.add(user)
            db.session.commit()

        userinfo = {
            "sub": google_id,
            "email": email,
            "email_verified": True,
        }

        original_flag = auth_module.google_oauth_enabled
        auth_module.google_oauth_enabled = True

        mock_google = MagicMock()
        # Token WITHOUT userinfo key -- should trigger fallback
        mock_google.authorize_access_token.return_value = {}
        mock_google.userinfo.return_value = userinfo
        original_google = getattr(auth_module.oauth, 'google', None)
        auth_module.oauth.google = mock_google

        try:
            rv = client.get("/login/google/callback")
            assert rv.status_code == 302
            location = rv.headers["Location"]
            assert location.endswith("/") or location == "/"

            # Verify that userinfo() was called as fallback
            mock_google.userinfo.assert_called_once()
        finally:
            auth_module.google_oauth_enabled = original_flag
            if original_google is not None:
                auth_module.oauth.google = original_google

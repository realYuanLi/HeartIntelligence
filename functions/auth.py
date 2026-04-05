"""Authentication module for DREAM-Chat.

Provides email-based user authentication with Flask-Login session management,
Flask-SQLAlchemy ORM, and werkzeug password hashing. Includes a User model
with a tier field for future subscription support.
"""

import os
import re
import secrets
import logging
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for, jsonify
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()

# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    """Application user stored in SQLite."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    tier = db.Column(db.String(32), nullable=False, default="base")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# Flask-Login callback
# ---------------------------------------------------------------------------

@login_manager.user_loader
def _load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(raw: str) -> str:
    """Strip whitespace and lowercase an email address."""
    return raw.strip().lower()


def _generate_csrf_token() -> str:
    """Return the current session's CSRF token, creating one if needed."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def _validate_csrf_token() -> bool:
    """Check that the submitted CSRF token matches the session token."""
    token = request.form.get("_csrf_token", "")
    return token == session.get("_csrf_token", None)


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render login form (GET) or authenticate user (POST)."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        if not _validate_csrf_token():
            flash("Invalid form submission. Please try again.", "error")
            return render_template("login.html", csrf_token=_generate_csrf_token())

        email = _normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html", csrf_token=_generate_csrf_token())

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("login.html", csrf_token=_generate_csrf_token())

        login_user(user)
        session["username"] = user.email
        logger.info("User logged in: %s", user.email)
        return redirect(url_for("index"))

    return render_template("login.html", csrf_token=_generate_csrf_token())


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Render registration form (GET) or create new account (POST)."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        if not _validate_csrf_token():
            flash("Invalid form submission. Please try again.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        invite_code = request.form.get("invite_code", "").strip()
        if invite_code != "INVITE":
            flash("Invalid invite code.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        email = _normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not email or not password or not confirm_password:
            flash("All fields are required.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        if not _EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        if User.query.filter_by(email=email).first() is not None:
            flash("An account with this email already exists.", "error")
            return render_template("register.html", csrf_token=_generate_csrf_token())

        tier = request.form.get("tier", "base")
        if tier not in ("base", "premium"):
            tier = "base"

        user = User(email=email, tier=tier)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("New user registered: %s", user.email)

        login_user(user)
        session["username"] = user.email
        return redirect(url_for("index"))

    return render_template("register.html", csrf_token=_generate_csrf_token())


@auth_bp.route("/logout")
def logout():
    """Log out the current user and redirect to login page."""
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# JSON API endpoints (backward compatibility)
# ---------------------------------------------------------------------------

@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """JSON login endpoint for AJAX clients."""
    if not request.content_type or "application/json" not in request.content_type:
        return jsonify(success=False, message="Content-Type must be application/json."), 415
    data = request.get_json(force=True)
    email = _normalize_email(data.get("email") or data.get("username") or "")
    password = data.get("password", "")

    if not email or not password:
        return jsonify(success=False, message="Email and password are required."), 400

    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(password):
        return jsonify(success=False, message="Invalid email or password."), 401

    login_user(user)
    session["username"] = user.email
    return jsonify(success=True, email=user.email)


@auth_bp.route("/api/logout", methods=["POST"])
def api_logout():
    """JSON logout endpoint for AJAX clients."""
    if not request.content_type or "application/json" not in request.content_type:
        return jsonify(success=False, message="Content-Type must be application/json."), 415
    logout_user()
    session.clear()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# Shared secret for WhatsApp bridge
# ---------------------------------------------------------------------------

def _write_bot_secret(password: str) -> None:
    """Write the bot password to whatsapp/store/.bot_secret for the Node.js bridge."""
    from pathlib import Path

    secret_dir = Path(__file__).resolve().parent.parent / "whatsapp" / "store"
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_file = secret_dir / ".bot_secret"
    secret_file.write_text(password, encoding="utf-8")
    secret_file.chmod(0o600)
    logger.info("Wrote shared bot secret to %s", secret_file)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_auth(app) -> None:
    """Initialize authentication subsystem on the Flask app.

    - Configures SQLAlchemy with SQLite at ``instance/dream_chat.db``
    - Initializes Flask-Login
    - Creates database tables
    - Seeds a demo user if the database is empty
    """
    # SECRET_KEY is set in app.py — do not duplicate it here.
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///dream_chat.db")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    with app.app_context():
        db.create_all()

        # Seed a demo user when the database is brand new
        if User.query.count() == 0:
            demo = User(email="demo@example.com", tier="free")
            demo.set_password("demo123")
            db.session.add(demo)
            db.session.commit()
            logger.info("Seeded demo user: demo@example.com / demo123")

        # Ensure the WhatsApp bridge service account exists
        bot_email = "bot@dreamchat.local"
        bot_password = os.environ.get("BOT_PASSWORD", "")
        if User.query.filter_by(email=bot_email).first() is None:
            if not bot_password:
                bot_password = secrets.token_urlsafe(16)
                logger.info(
                    "BOT_PASSWORD env var not set — auto-generated for %s",
                    bot_email,
                )
            bot = User(email=bot_email, tier="service")
            bot.set_password(bot_password)
            db.session.add(bot)
            db.session.commit()
            logger.info("Seeded service account: %s", bot_email)
        else:
            bot_user = User.query.filter_by(email=bot_email).first()
            if bot_password:
                # Env var is set — sync the DB hash to match it.
                bot_user.set_password(bot_password)
                db.session.commit()
            else:
                # No env var — auto-generate and update the service account.
                bot_password = secrets.token_urlsafe(16)
                bot_user.set_password(bot_password)
                db.session.commit()
                logger.info("Rotated auto-generated BOT_PASSWORD for %s", bot_email)

        # Write the bot password to a shared secret file so the Node.js
        # WhatsApp bridge can read it without manual .env configuration.
        _write_bot_secret(bot_password)

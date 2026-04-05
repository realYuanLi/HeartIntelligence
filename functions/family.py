"""Family module for DREAM-Chat.

Lets users build a family circle: invite members by email, accept/decline
invitations, and share health summaries with accepted family members.
All data lives in the existing SQLite database via SQLAlchemy.
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from functions.auth import db, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class FamilyLink(db.Model):
    """A directed relationship between two users in a family circle."""

    __tablename__ = "family_links"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    member_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    invited_email = db.Column(db.String(254), nullable=False)
    relationship = db.Column(db.String(64), nullable=False, default="family")
    status = db.Column(db.String(16), nullable=False, default="pending")  # pending | accepted | declined
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    owner = db.relationship("User", foreign_keys=[owner_id], backref="family_sent")
    member = db.relationship("User", foreign_keys=[member_id], backref="family_received")


class FamilyShare(db.Model):
    """A health summary shared with a family member."""

    __tablename__ = "family_shares"

    id = db.Column(db.Integer, primary_key=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    sender = db.relationship("User", foreign_keys=[from_user_id])
    receiver = db.relationship("User", foreign_keys=[to_user_id])


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

family_bp = Blueprint("family", __name__)


@family_bp.route("/family")
@login_required
def family_page():
    return render_template("family.html", username=current_user.email)


# ---------------------------------------------------------------------------
# API: list family members
# ---------------------------------------------------------------------------

@family_bp.route("/api/family/members")
@login_required
def list_members():
    """Return the current user's family circle (sent + received links)."""
    uid = current_user.id

    sent = FamilyLink.query.filter_by(owner_id=uid).all()
    received = FamilyLink.query.filter(
        FamilyLink.member_id == uid,
        FamilyLink.status == "accepted",
    ).all()

    members = []
    for link in sent:
        members.append({
            "id": link.id,
            "email": link.invited_email,
            "relationship": link.relationship,
            "status": link.status,
            "direction": "sent",
            "created_at": link.created_at.isoformat(),
        })
    for link in received:
        members.append({
            "id": link.id,
            "email": link.owner.email,
            "relationship": link.relationship,
            "status": "accepted",
            "direction": "received",
            "created_at": link.created_at.isoformat(),
        })

    # Pending invitations addressed to me (by email)
    pending = FamilyLink.query.filter(
        FamilyLink.invited_email == current_user.email,
        FamilyLink.status == "pending",
    ).all()
    invitations = [
        {
            "id": p.id,
            "from_email": p.owner.email,
            "relationship": p.relationship,
            "created_at": p.created_at.isoformat(),
        }
        for p in pending
    ]

    return jsonify(success=True, members=members, invitations=invitations)


# ---------------------------------------------------------------------------
# API: invite a family member
# ---------------------------------------------------------------------------

@family_bp.route("/api/family/invite", methods=["POST"])
@login_required
def invite_member():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    relationship = (data.get("relationship") or "family").strip()

    if not email:
        return jsonify(success=False, message="Email is required."), 400
    if email == current_user.email:
        return jsonify(success=False, message="You cannot invite yourself."), 400

    # Prevent duplicate pending invites
    existing = FamilyLink.query.filter_by(
        owner_id=current_user.id, invited_email=email
    ).filter(FamilyLink.status.in_(["pending", "accepted"])).first()
    if existing:
        return jsonify(success=False, message="Already invited or connected."), 409

    member = User.query.filter_by(email=email).first()
    link = FamilyLink(
        owner_id=current_user.id,
        member_id=member.id if member else None,
        invited_email=email,
        relationship=relationship,
    )
    db.session.add(link)
    db.session.commit()
    logger.info("Family invite sent: %s -> %s", current_user.email, email)
    return jsonify(success=True, link_id=link.id)


# ---------------------------------------------------------------------------
# API: respond to an invitation (accept / decline)
# ---------------------------------------------------------------------------

@family_bp.route("/api/family/respond", methods=["POST"])
@login_required
def respond_invitation():
    data = request.get_json(force=True)
    link_id = data.get("link_id")
    action = data.get("action")  # "accept" or "decline"

    if action not in ("accept", "decline"):
        return jsonify(success=False, message="Action must be accept or decline."), 400

    link = FamilyLink.query.get(link_id)
    if not link or link.invited_email != current_user.email or link.status != "pending":
        return jsonify(success=False, message="Invitation not found."), 404

    if action == "accept":
        link.status = "accepted"
        link.member_id = current_user.id
    else:
        link.status = "declined"

    db.session.commit()
    logger.info("Family invite %s: %s (link %d)", action, current_user.email, link.id)
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# API: remove a family link
# ---------------------------------------------------------------------------

@family_bp.route("/api/family/remove", methods=["POST"])
@login_required
def remove_member():
    data = request.get_json(force=True)
    link_id = data.get("link_id")

    link = FamilyLink.query.get(link_id)
    if not link:
        return jsonify(success=False, message="Link not found."), 404

    # Either side can remove
    if link.owner_id != current_user.id and link.member_id != current_user.id:
        return jsonify(success=False, message="Not authorized."), 403

    db.session.delete(link)
    db.session.commit()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# API: share a health summary with a family member
# ---------------------------------------------------------------------------

@family_bp.route("/api/family/share", methods=["POST"])
@login_required
def share_summary():
    data = request.get_json(force=True)
    to_email = (data.get("to_email") or "").strip().lower()
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()

    if not to_email or not title or not body:
        return jsonify(success=False, message="to_email, title, and body are required."), 400

    # Verify accepted family link exists
    to_user = User.query.filter_by(email=to_email).first()
    if not to_user:
        return jsonify(success=False, message="User not found."), 404

    link = FamilyLink.query.filter(
        (
            (FamilyLink.owner_id == current_user.id) & (FamilyLink.member_id == to_user.id)
        ) | (
            (FamilyLink.owner_id == to_user.id) & (FamilyLink.member_id == current_user.id)
        ),
        FamilyLink.status == "accepted",
    ).first()
    if not link:
        return jsonify(success=False, message="Not a connected family member."), 403

    share = FamilyShare(
        from_user_id=current_user.id,
        to_user_id=to_user.id,
        title=title,
        body=body,
    )
    db.session.add(share)
    db.session.commit()
    return jsonify(success=True, share_id=share.id)


# ---------------------------------------------------------------------------
# API: view shared summaries
# ---------------------------------------------------------------------------

@family_bp.route("/api/family/shared")
@login_required
def list_shared():
    """Summaries shared with me and summaries I've sent."""
    received = FamilyShare.query.filter_by(to_user_id=current_user.id).order_by(
        FamilyShare.created_at.desc()
    ).limit(50).all()
    sent = FamilyShare.query.filter_by(from_user_id=current_user.id).order_by(
        FamilyShare.created_at.desc()
    ).limit(50).all()

    return jsonify(
        success=True,
        received=[
            {
                "id": s.id,
                "from_email": s.sender.email,
                "title": s.title,
                "body": s.body,
                "created_at": s.created_at.isoformat(),
            }
            for s in received
        ],
        sent=[
            {
                "id": s.id,
                "to_email": s.receiver.email,
                "title": s.title,
                "body": s.body,
                "created_at": s.created_at.isoformat(),
            }
            for s in sent
        ],
    )

"""Community module for DREAM-Chat.

Provides lightweight health-focused community groups where users can create
or join groups, post updates/milestones, and browse a simple activity feed.
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

class Community(db.Model):
    """A health-focused community group."""

    __tablename__ = "communities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    topic = db.Column(db.String(64), nullable=False, default="general")  # e.g. fitness, nutrition, mental-health
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship("User", backref="communities_created")
    members = db.relationship("CommunityMember", backref="community", cascade="all, delete-orphan")
    posts = db.relationship("CommunityPost", backref="community", cascade="all, delete-orphan")


class CommunityMember(db.Model):
    """Membership in a community."""

    __tablename__ = "community_members"

    id = db.Column(db.Integer, primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey("communities.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False, default="member")  # member | admin
    joined_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="community_memberships")

    __table_args__ = (
        db.UniqueConstraint("community_id", "user_id", name="uq_community_user"),
    )


class CommunityPost(db.Model):
    """A post/update in a community feed."""

    __tablename__ = "community_posts"

    id = db.Column(db.Integer, primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey("communities.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    author = db.relationship("User", backref="community_posts")


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

community_bp = Blueprint("community", __name__)


@community_bp.route("/community")
@login_required
def community_page():
    return render_template("community.html", username=current_user.email)


# ---------------------------------------------------------------------------
# API: list communities (all + mine)
# ---------------------------------------------------------------------------

@community_bp.route("/api/community/list")
@login_required
def list_communities():
    my_ids = {
        m.community_id
        for m in CommunityMember.query.filter_by(user_id=current_user.id).all()
    }

    all_communities = Community.query.order_by(Community.created_at.desc()).limit(100).all()
    result = []
    for c in all_communities:
        result.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "topic": c.topic,
            "created_by": c.creator.email,
            "member_count": len(c.members),
            "is_member": c.id in my_ids,
            "created_at": c.created_at.isoformat(),
        })
    return jsonify(success=True, communities=result)


# ---------------------------------------------------------------------------
# API: create a community
# ---------------------------------------------------------------------------

@community_bp.route("/api/community/create", methods=["POST"])
@login_required
def create_community():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    topic = (data.get("topic") or "general").strip().lower()

    if not name:
        return jsonify(success=False, message="Community name is required."), 400
    if len(name) > 120:
        return jsonify(success=False, message="Name too long (max 120 chars)."), 400

    community = Community(
        name=name,
        description=description,
        topic=topic,
        created_by=current_user.id,
    )
    db.session.add(community)
    db.session.flush()  # get community.id

    # Creator is auto-joined as admin
    membership = CommunityMember(
        community_id=community.id,
        user_id=current_user.id,
        role="admin",
    )
    db.session.add(membership)
    db.session.commit()

    logger.info("Community created: %s by %s", name, current_user.email)
    return jsonify(success=True, community_id=community.id)


# ---------------------------------------------------------------------------
# API: join / leave
# ---------------------------------------------------------------------------

@community_bp.route("/api/community/<int:cid>/join", methods=["POST"])
@login_required
def join_community(cid):
    community = Community.query.get(cid)
    if not community:
        return jsonify(success=False, message="Community not found."), 404

    existing = CommunityMember.query.filter_by(
        community_id=cid, user_id=current_user.id
    ).first()
    if existing:
        return jsonify(success=False, message="Already a member."), 409

    db.session.add(CommunityMember(community_id=cid, user_id=current_user.id))
    db.session.commit()
    return jsonify(success=True)


@community_bp.route("/api/community/<int:cid>/leave", methods=["POST"])
@login_required
def leave_community(cid):
    membership = CommunityMember.query.filter_by(
        community_id=cid, user_id=current_user.id
    ).first()
    if not membership:
        return jsonify(success=False, message="Not a member."), 404

    db.session.delete(membership)
    db.session.commit()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# API: community feed (posts)
# ---------------------------------------------------------------------------

@community_bp.route("/api/community/<int:cid>/feed")
@login_required
def community_feed(cid):
    community = Community.query.get(cid)
    if not community:
        return jsonify(success=False, message="Community not found."), 404

    posts = (
        CommunityPost.query
        .filter_by(community_id=cid)
        .order_by(CommunityPost.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify(
        success=True,
        community={
            "id": community.id,
            "name": community.name,
            "description": community.description,
            "topic": community.topic,
            "member_count": len(community.members),
        },
        posts=[
            {
                "id": p.id,
                "author": p.author.email,
                "content": p.content,
                "created_at": p.created_at.isoformat(),
            }
            for p in posts
        ],
    )


# ---------------------------------------------------------------------------
# API: create a post
# ---------------------------------------------------------------------------

@community_bp.route("/api/community/<int:cid>/post", methods=["POST"])
@login_required
def create_post(cid):
    # Must be a member to post
    membership = CommunityMember.query.filter_by(
        community_id=cid, user_id=current_user.id
    ).first()
    if not membership:
        return jsonify(success=False, message="Join the community first."), 403

    data = request.get_json(force=True)
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify(success=False, message="Post content is required."), 400
    if len(content) > 2000:
        return jsonify(success=False, message="Post too long (max 2000 chars)."), 400

    post = CommunityPost(
        community_id=cid,
        user_id=current_user.id,
        content=content,
    )
    db.session.add(post)
    db.session.commit()
    return jsonify(success=True, post_id=post.id)

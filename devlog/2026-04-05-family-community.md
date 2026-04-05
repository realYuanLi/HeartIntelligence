# Family & Community Features

**Date**: 2026-04-05  |  **Status**: Completed

## What Was Built
Minimal but functional family circle and community features for demo purposes. Users can invite family members by email, accept/decline invitations, share health summaries, and participate in topic-based community groups with a simple post feed.

## Architecture
Two new Flask blueprints (`family_bp`, `community_bp`) with SQLAlchemy models stored in the existing SQLite database. Each blueprint owns its own page route, API endpoints, template, and frontend JS. No pseudo data — all state is persisted in the DB.

## Key Files
| File | Purpose |
|------|---------|
| `functions/family.py` | FamilyLink + FamilyShare models, invite/respond/share APIs |
| `functions/community.py` | Community + CommunityMember + CommunityPost models, CRUD APIs |
| `templates/family.html` | Family circle page (invite, members, shared summaries) |
| `templates/community.html` | Community page (create, browse, join, feed) |
| `static/family.js` | Family frontend interactions |
| `static/community.js` | Community frontend interactions |

## Technical Decisions
- Reused existing `db` (SQLAlchemy) and `User` model — no new dependencies.
- Family links are directional (owner invites member); either side can remove.
- Community posts are simple text — no rich media for MVP.
- `db.create_all()` called after blueprint registration to auto-migrate.

## Usage
Navigate to **Family** or **Community** in the sidebar. Invite family by email, create communities by topic, post updates to group feeds.

## Known Limitations
- No real-time notifications for invitations or posts (poll-based).
- No admin controls for community moderation beyond creator role.
- Share summaries are manually typed, not auto-generated from health data.

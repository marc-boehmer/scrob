"""announce language setting move and email change flow

Revision ID: notifications14
Revises: notifications13
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "notifications14"
down_revision = "notifications13"
branch_labels = None
depends_on = None

TITLE = "Language setting moved, safer email changes"
BODY = (
    "The interface language now lives in Profile Settings under Interface language. "
    "Changing your email address now sends a confirmation link to the new address, "
    "and the address only changes once you confirm it. Your Watchlist, friends and "
    "privacy settings work as before."
)
# Used when another announcement already exists for this version (same deploy).
APPENDED = f"\n\n{TITLE}: {BODY}"


def upgrade() -> None:
    bind = op.get_bind()
    version = os.environ.get("APP_VERSION", "dev").strip() or "dev"

    bind.execute(
        sa.text(
            """
            INSERT INTO release_announcements (version, title, body)
            VALUES (:version, :title, :body)
            ON CONFLICT (version) DO UPDATE
            SET body = release_announcements.body || :appended
            WHERE position(:body in release_announcements.body) = 0
            """
        ),
        {"version": version, "title": TITLE, "body": BODY, "appended": APPENDED},
    )
    announcement_id = bind.execute(
        sa.text("SELECT id FROM release_announcements WHERE version = :version"),
        {"version": version},
    ).scalar_one()

    bind.execute(
        sa.text(
            """
            INSERT INTO notifications (user_id, actor_id, type, release_announcement_id, is_read)
            SELECT users.id, NULL, 'release_announcement', :announcement_id, false
            FROM users
            WHERE NOT EXISTS (
                SELECT 1
                FROM notifications
                WHERE notifications.user_id = users.id
                  AND notifications.release_announcement_id = :announcement_id
            )
            """
        ),
        {"announcement_id": announcement_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM release_announcements WHERE title = :title AND body = :body"),
        {"title": TITLE, "body": BODY},
    )
    bind.execute(
        sa.text(
            "UPDATE release_announcements SET body = replace(body, :appended, '') "
            "WHERE position(:appended in body) > 0"
        ),
        {"appended": APPENDED},
    )

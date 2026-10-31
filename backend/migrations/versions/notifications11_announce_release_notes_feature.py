"""announce release notes feature

Revision ID: notifications11
Revises: notifications10
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "notifications11"
down_revision = "notifications10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    version = os.environ.get("APP_VERSION", "dev").strip() or "dev"
    title = "Release notes are now in Scrob"
    body = (
        "Scrob now has in-app release announcements. When a new version is deployed, "
        "you can read what's changed by opening its notification from the bell menu."
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO release_announcements (version, title, body)
            VALUES (:version, :title, :body)
            ON CONFLICT (version) DO NOTHING
            """
        ),
        {"version": version, "title": title, "body": body},
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
        {
            "title": "Release notes are now in Scrob",
            "body": (
                "Scrob now has in-app release announcements. When a new version is deployed, "
                "you can read what's changed by opening its notification from the bell menu."
            ),
        },
    )

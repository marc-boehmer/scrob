"""announce German interface translation

Revision ID: notifications15
Revises: notifications14
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "notifications15"
down_revision = "notifications14"
branch_labels = None
depends_on = None

TITLE = "German interface translation"
BODY = (
    "Scrob is now available in German. Choose Deutsch under "
    "Profile Settings -> Interface language."
)
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

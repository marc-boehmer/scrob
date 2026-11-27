"""announce translations, filters, stats and item details; merge migration heads

Revision ID: notifications13
Revises: notifications12, uilang
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "notifications13"
down_revision = ("notifications12", "uilang")
branch_labels = None
depends_on = None

TITLE = "Translations, saved filters, statistics and richer item pages"
BODY = (
    "Scrob can now be shown in French and Portuguese (choose it in Profile Settings). "
    "The Explore filters gained saved filters, excluding genres or languages and a "
    "my-rating filter. There are new statistics pages, and movie and show pages now "
    "show watch stats, release status and where to watch."
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

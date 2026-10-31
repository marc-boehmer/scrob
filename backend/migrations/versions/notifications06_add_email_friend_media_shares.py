"""add friend media-share email preference

Revision ID: notifications06
Revises: notifications05
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications06"
down_revision = "notifications05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("email_friend_media_shares", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "email_friend_media_shares")

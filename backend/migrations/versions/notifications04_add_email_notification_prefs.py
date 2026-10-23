"""add email notification preferences to user_settings

Revision ID: notifications04
Revises: notifications03
Create Date: 2026-10-24
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications04"
down_revision = "notifications03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("email_friend_requests", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "user_settings",
        sa.Column("email_rating_digest", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "email_rating_digest")
    op.drop_column("user_settings", "email_friend_requests")

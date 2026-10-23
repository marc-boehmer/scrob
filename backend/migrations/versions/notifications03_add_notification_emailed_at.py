"""add notifications.emailed_at

Revision ID: notifications03
Revises: notifications02
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications03"
down_revision = "notifications02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("emailed_at", sa.DateTime(), nullable=True))
    # Existing notifications predate email delivery; don't mail them out as a backlog.
    op.execute("UPDATE notifications SET emailed_at = now()")


def downgrade() -> None:
    op.drop_column("notifications", "emailed_at")

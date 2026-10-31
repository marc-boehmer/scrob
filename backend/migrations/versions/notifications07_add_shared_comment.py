"""add optional comment to shared-media notifications

Revision ID: notifications07
Revises: notifications06
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications07"
down_revision = "notifications06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("shared_comment", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "shared_comment")

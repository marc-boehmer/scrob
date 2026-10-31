"""add shared media details to notifications

Revision ID: notifications05
Revises: notifications04
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications05"
down_revision = "notifications04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("shared_media_title", sa.String(length=500), nullable=True))
    op.add_column("notifications", sa.Column("shared_media_link", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "shared_media_link")
    op.drop_column("notifications", "shared_media_title")

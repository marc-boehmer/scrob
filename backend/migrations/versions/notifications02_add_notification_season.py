"""add season_number to notifications

Revision ID: notifications02
Revises: notifications01
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications02"
down_revision = "notifications01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("season_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "season_number")

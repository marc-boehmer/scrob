"""Allow system notifications without an actor

Revision ID: notifications09
Revises: notifications08
"""
from alembic import op

revision = "notifications09"
down_revision = "notifications08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("notifications", "actor_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE actor_id IS NULL")
    op.alter_column("notifications", "actor_id", nullable=False)

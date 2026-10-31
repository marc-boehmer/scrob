"""add release announcements and notification references

Revision ID: notifications10
Revises: notifications09
"""

from alembic import op
import sqlalchemy as sa


revision = "notifications10"
down_revision = "notifications09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("version", name="uq_release_announcements_version"),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "release_announcement_id",
            sa.Integer(),
            sa.ForeignKey("release_announcements.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("notifications", "release_announcement_id")
    op.drop_table("release_announcements")

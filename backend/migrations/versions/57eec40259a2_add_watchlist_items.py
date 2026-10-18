"""add watchlist_items

Revision ID: 57eec40259a2
Revises: simkldrop
"""

from alembic import op
import sqlalchemy as sa


revision = "57eec40259a2"
down_revision = "simkldrop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "media_id", name="uq_watchlist_user_media"),
    )
    op.create_index("ix_watchlist_items_media_id", "watchlist_items", ["media_id"], unique=False)
    op.create_index("ix_watchlist_items_user_id", "watchlist_items", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_user_id", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_media_id", table_name="watchlist_items")
    op.drop_table("watchlist_items")

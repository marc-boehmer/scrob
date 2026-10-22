"""add friendships and default new profiles to friends_only

Revision ID: friendships01
Revises: 57eec40259a2
"""

from alembic import op
import sqlalchemy as sa


revision = "friendships01"
down_revision = "57eec40259a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("addressee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friendship"),
    )
    op.create_index("ix_friendships_requester_id", "friendships", ["requester_id"])
    op.create_index("ix_friendships_addressee_id", "friendships", ["addressee_id"])

    # Existing mutual follows become friendships so nobody loses access.
    op.execute(
        """
        INSERT INTO friendships (requester_id, addressee_id, status)
        SELECT f1.follower_id, f1.following_id, 'accepted'
        FROM follows f1
        JOIN follows f2
          ON f2.follower_id = f1.following_id AND f2.following_id = f1.follower_id
        WHERE f1.follower_id < f1.following_id
        """
    )

    op.execute("ALTER TABLE user_profiles ALTER COLUMN privacy_level SET DEFAULT 'friends_only'")


def downgrade() -> None:
    op.execute("ALTER TABLE user_profiles ALTER COLUMN privacy_level SET DEFAULT 'private'")
    op.drop_index("ix_friendships_addressee_id", table_name="friendships")
    op.drop_index("ix_friendships_requester_id", table_name="friendships")
    op.drop_table("friendships")

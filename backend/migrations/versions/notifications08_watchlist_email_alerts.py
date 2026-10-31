"""add watchlist release and streaming email alerts

Revision ID: notifications08
Revises: notifications07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "notifications08"
down_revision = "notifications07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("email_watchlist_release_dates", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "user_settings",
        sa.Column("email_watchlist_streaming", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "watchlist_alert_states",
        sa.Column(
            "watchlist_item_id",
            sa.Integer(),
            sa.ForeignKey("watchlist_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("release_notified_at", sa.DateTime(), nullable=True),
        sa.Column("streaming_provider_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("streaming_country", sa.String(length=2), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        """
        INSERT INTO watchlist_alert_states (watchlist_item_id, release_notified_at)
        SELECT watchlist_items.id,
               CASE
                   WHEN media.release_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                        AND media.release_date <= CURRENT_DATE::text
                   THEN CURRENT_TIMESTAMP
                   ELSE NULL
               END
        FROM watchlist_items
        JOIN media ON media.id = watchlist_items.media_id
        WHERE media.tmdb_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("watchlist_alert_states")
    op.drop_column("user_settings", "email_watchlist_streaming")
    op.drop_column("user_settings", "email_watchlist_release_dates")

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WatchlistAlertState(Base):
    __tablename__ = "watchlist_alert_states"

    watchlist_item_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_items.id", ondelete="CASCADE"), primary_key=True
    )
    release_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    streaming_provider_ids: Mapped[Optional[list[int]]] = mapped_column(JSONB, nullable=True)
    streaming_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

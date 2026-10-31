from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Notification(Base):
    """An in-app friend request, rating, or media-share notification for `user_id`."""
    __tablename__ = "notifications"

    id         : Mapped[int]             = mapped_column(Integer, primary_key=True)
    user_id    : Mapped[int]             = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id   : Mapped[Optional[int]]   = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    type       : Mapped[str]             = mapped_column(String(32), nullable=False)
    media_id   : Mapped[Optional[int]]   = mapped_column(ForeignKey("media.id", ondelete="CASCADE"), nullable=True)
    season_number : Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating     : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shared_media_title : Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    shared_media_link  : Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    shared_comment     : Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_read    : Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at : Mapped[datetime]        = mapped_column(DateTime, server_default=func.now(), nullable=False)
    emailed_at : Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

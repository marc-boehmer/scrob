from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.watchlist_alerts import WATCHLIST_RELEASE, WATCHLIST_STREAMING
from core.notifications import FRIEND_MEDIA_SHARE, email_friend_media_share, sender_media_rating
from db import get_db
from dependencies import get_current_user
from models.friendship import Friendship
from models.media import Media
from models.notification import Notification
from models.users import User
from routers.friends import _people

router = APIRouter()

LIST_LIMIT = 30
WATCHLIST_TYPES = {WATCHLIST_RELEASE, WATCHLIST_STREAMING}


class MediaShareRequest(BaseModel):
    recipient_ids: list[int] = Field(min_length=1, max_length=20)
    media_type: Literal["movie", "series"]
    title: str = Field(min_length=1, max_length=500)
    tmdb_id: int | None = Field(default=None, gt=0)
    tvdb_id: int | None = Field(default=None, gt=0)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("recipient_ids")
    @classmethod
    def unique_positive_recipients(cls, ids: list[int]) -> list[int]:
        if any(user_id <= 0 for user_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("Recipient IDs must be unique positive integers.")
        return ids

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("Title cannot be blank.")
        return title

    @field_validator("comment")
    @classmethod
    def blank_comment_is_none(cls, comment: str | None) -> str | None:
        return (comment or "").strip() or None

    @model_validator(mode="after")
    def valid_media_identity(self):
        if self.media_type == "movie" and self.tmdb_id is None:
            raise ValueError("Movies require a TMDB ID.")
        if self.media_type == "series" and self.tmdb_id is None and self.tvdb_id is None:
            raise ValueError("Shows require a TMDB or TVDB ID.")
        return self


def _media_link(media: Media, season_number: int | None) -> str | None:
    if media.media_type == "movie":
        return f"/movie/{media.tmdb_id}" if media.tmdb_id else None
    show = media.show if media.media_type == "episode" else media
    if not show or not (show.tmdb_id or show.tvdb_id):
        return None
    base = f"/show/{show.tmdb_id}" if show.tmdb_id else f"/show/tvdb/{show.tvdb_id}"
    if media.media_type == "episode" and media.season_number is not None and media.episode_number is not None:
        return f"{base}/season/{media.season_number}/{media.episode_number}"
    if season_number is not None:
        return f"{base}/season/{season_number}"
    return base


def _notification_media(notification: Notification, media: Media | None) -> dict | None:
    if media:
        return {
            "title": (media.show.title if media.media_type == "episode" and media.show else media.title),
            "type": media.media_type.value if hasattr(media.media_type, "value") else media.media_type,
            "season_number": notification.season_number if notification.season_number is not None else media.season_number,
            "episode_number": media.episode_number,
            "link": _media_link(media, notification.season_number),
        }
    if notification.shared_media_title and notification.shared_media_link:
        return {
            "title": notification.shared_media_title,
            "type": "shared",
            "season_number": None,
            "episode_number": None,
            "link": notification.shared_media_link,
        }
    return None


async def _unread_count(db: AsyncSession, user_id: int) -> int:
    return (await db.execute(
        select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.is_read.is_(False))
    )).scalar_one()


@router.get("")
async def list_notifications(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(LIST_LIMIT)
    )).scalars().all()

    people = await _people(db, list({n.actor_id for n in rows if n.actor_id}))
    media_ids = [n.media_id for n in rows if n.media_id]
    media = {}
    if media_ids:
        media = {m.id: m for m in (await db.execute(select(Media).options(selectinload(Media.show)).where(Media.id.in_(media_ids)))).scalars().all()}

    items = []
    for n in rows:
        actor = people.get(n.actor_id) if n.actor_id else None
        if not actor and n.type not in WATCHLIST_TYPES:
            continue
        m = media.get(n.media_id) if n.media_id else None
        items.append({
            "id": n.id,
            "type": n.type,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
            "actor": actor,
            "rating": n.rating,
            "comment": n.shared_comment,
            "media": _notification_media(n, m),
        })
    return {"notifications": items, "unread_count": await _unread_count(db, current_user.id)}


@router.post("/share")
async def share_media(
    body: MediaShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id in body.recipient_ids:
        raise HTTPException(status_code=400, detail="You cannot share a title with yourself.")

    friendships = (await db.execute(
        select(Friendship).where(
            Friendship.status == "accepted",
            or_(
                and_(
                    Friendship.requester_id == current_user.id,
                    Friendship.addressee_id.in_(body.recipient_ids),
                ),
                and_(
                    Friendship.addressee_id == current_user.id,
                    Friendship.requester_id.in_(body.recipient_ids),
                ),
            ),
        )
    )).scalars().all()
    accepted_ids = {
        f.addressee_id if f.requester_id == current_user.id else f.requester_id
        for f in friendships
    }
    if accepted_ids != set(body.recipient_ids):
        raise HTTPException(status_code=403, detail="You can only share titles with accepted friends.")

    if body.media_type == "movie":
        link = f"/movie/{body.tmdb_id}"
    elif body.tmdb_id is not None:
        link = f"/show/{body.tmdb_id}"
    else:
        link = f"/show/tvdb/{body.tvdb_id}"

    rating = await sender_media_rating(db, current_user.id, body.media_type, body.tmdb_id, body.tvdb_id)
    for recipient_id in body.recipient_ids:
        db.add(Notification(
            user_id=recipient_id,
            actor_id=current_user.id,
            type=FRIEND_MEDIA_SHARE,
            shared_media_title=body.title,
            shared_media_link=link,
            shared_comment=body.comment,
            rating=rating,
        ))
    await db.commit()
    for recipient_id in body.recipient_ids:
        await email_friend_media_share(db, current_user.id, recipient_id, body.title, link, rating, body.comment)
    return {"sent": len(body.recipient_ids)}


@router.get("/share-rating")
async def share_rating(
    media_type: Literal["movie", "series"],
    tmdb_id: int | None = None,
    tvdb_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if tmdb_id is None and tvdb_id is None:
        raise HTTPException(status_code=400, detail="A TMDB or TVDB ID is required.")
    return {"rating": await sender_media_rating(db, current_user.id, media_type, tmdb_id, tvdb_id)}


@router.get("/unread-count")
async def unread_count(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"unread_count": await _unread_count(db, current_user.id)}


@router.post("/read-all")
async def mark_all_read(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return {"unread_count": 0}


@router.delete("")
async def clear_all(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Notification).where(Notification.user_id == current_user.id))
    await db.commit()
    return {"unread_count": 0}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == current_user.id)
        .values(is_read=True)
    )
    await db.commit()
    return {"unread_count": await _unread_count(db, current_user.id)}

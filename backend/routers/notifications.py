from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db import get_db
from dependencies import get_current_user
from models.media import Media
from models.notification import Notification
from models.users import User
from routers.friends import _people

router = APIRouter()

LIST_LIMIT = 30


def _media_link(media: Media, season_number: int | None) -> str | None:
    if media.media_type == "movie":
        return f"/media/movie/{media.tmdb_id}" if media.tmdb_id else None
    show = media.show if media.media_type == "episode" else media
    if not show or not (show.tmdb_id or show.tvdb_id):
        return None
    base = f"/show/{show.tmdb_id}" if show.tmdb_id else f"/show/tvdb/{show.tvdb_id}"
    if media.media_type == "episode" and media.season_number is not None and media.episode_number is not None:
        return f"{base}/season/{media.season_number}/{media.episode_number}"
    if season_number is not None:
        return f"{base}/season/{season_number}"
    return base


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

    people = await _people(db, list({n.actor_id for n in rows}))
    media_ids = [n.media_id for n in rows if n.media_id]
    media = {}
    if media_ids:
        media = {m.id: m for m in (await db.execute(select(Media).options(selectinload(Media.show)).where(Media.id.in_(media_ids)))).scalars().all()}

    items = []
    for n in rows:
        actor = people.get(n.actor_id)
        if not actor:
            continue
        m = media.get(n.media_id) if n.media_id else None
        items.append({
            "id": n.id,
            "type": n.type,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
            "actor": actor,
            "rating": n.rating,
            "media": {
                "title": (m.show.title if m.media_type == "episode" and m.show else m.title),
                "type": m.media_type.value if hasattr(m.media_type, "value") else m.media_type,
                "season_number": n.season_number if n.season_number is not None else m.season_number,
                "episode_number": m.episode_number,
                "link": _media_link(m, n.season_number),
            } if m else None,
        })
    return {"notifications": items, "unread_count": await _unread_count(db, current_user.id)}


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

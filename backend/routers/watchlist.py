from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies import get_current_user_or_api_key
from models.base import MediaType
from models.media import Media
from models.show import Show
from models.users import User
from models.watchlist import WatchlistItem
from routers.media import enrich_with_state

router = APIRouter()


async def _find_media(db: AsyncSession, media_type: MediaType, tmdb_id: int) -> Media | None:
    """The local Media row for a movie/series, if one exists. Ordered by id
    and limited so a rare duplicate row can't turn scalar_one_or_none into
    a 500 - same defensive pattern as history.py's next-up fallback."""
    return (await db.execute(
        select(Media)
        .where(Media.media_type == media_type, Media.tmdb_id == tmdb_id)
        .order_by(Media.id)
        .limit(1)
    )).scalars().first()


@router.get("")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Everything the user saved to watch later - same {movies, shows} split
    as the dropped page so the frontend reuses the same grid and cards."""
    result = await db.execute(
        select(Media, WatchlistItem.added_at)
        .join(WatchlistItem, WatchlistItem.media_id == Media.id)
        .where(WatchlistItem.user_id == current_user.id)
        .order_by(WatchlistItem.added_at.desc(), WatchlistItem.id.desc())
    )
    rows = result.all()

    # A series' status/season layout lives on its Show row, not on the Media
    # stub - batch-fetched via the shared tmdb_id rather than per-item joins.
    series_tmdb_ids = {
        m.tmdb_id for m, _ in rows
        if m.media_type == MediaType.series and m.tmdb_id
    }
    shows_by_tmdb: dict[int, Show] = {}
    if series_tmdb_ids:
        show_result = await db.execute(select(Show).where(Show.tmdb_id.in_(series_tmdb_ids)))
        shows_by_tmdb = {s.tmdb_id: s for s in show_result.scalars().all()}

    movies: list[dict] = []
    shows: list[dict] = []
    items: list[dict] = []
    for media, added_at in rows:
        item = {
            "id": media.id,
            "tmdb_id": media.tmdb_id, "tvdb_id": media.tvdb_id, "imdb_id": media.imdb_id,
            "type": media.media_type,
            "title": media.title,
            "overview": media.overview,
            "poster_path": media.poster_path,
            "backdrop_path": media.backdrop_path,
            "release_date": media.release_date,
            "tmdb_rating": media.tmdb_rating,
            "added_at": added_at.isoformat() if added_at else None,
        }
        if media.media_type == MediaType.movie:
            movies.append(item)
        else:
            show = shows_by_tmdb.get(media.tmdb_id) if media.tmdb_id else None
            item["status"] = show.status if show else None
            item["seasons"] = (show.tmdb_data or {}).get("seasons", []) if show else []
            shows.append(item)
        items.append(item)

    # Fills user_rating / in_library / watched (and "want" once media.py's
    # step lands) on the dicts in place - same call every listing makes.
    if items:
        await enrich_with_state(db, current_user.id, items)

    return {"movies": movies, "shows": shows}


class WatchlistToggleRequest(BaseModel):
    media_type: MediaType
    tmdb_id: int
    title: str = ""
    poster_path: str | None = None
    release_date: str | None = None


@router.post("/toggle")
async def toggle_watchlist(
    body: WatchlistToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    if body.media_type not in (MediaType.movie, MediaType.series):
        raise HTTPException(status_code=400, detail="media_type must be movie or series")

    media = await _find_media(db, body.media_type, body.tmdb_id)
    if media is None:
        if not body.title:
            raise HTTPException(status_code=400, detail="title is required to watchlist a new item")
        # Toggled from a browse/search card, where the title may have no local
        # row yet - create a minimal stub (same shape imports create) instead
        # of a live TMDB fetch; the detail page enriches it on first visit.
        media = Media(
            media_type=body.media_type,
            tmdb_id=body.tmdb_id,
            title=body.title,
            poster_path=body.poster_path,
            release_date=body.release_date,
        )
        try:
            async with db.begin_nested():
                db.add(media)
                await db.flush()
        except IntegrityError:
            # A concurrent request created the same row first - reuse it.
            media = await _find_media(db, body.media_type, body.tmdb_id)
            if media is None:
                raise HTTPException(status_code=409, detail="Could not resolve media row")

    existing = (await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id,
            WatchlistItem.media_id == media.id,
        )
    )).scalar_one_or_none()

    if existing is not None:
        await db.delete(existing)
        await db.commit()
        return {"status": "ok", "in_watchlist": False}

    try:
        async with db.begin_nested():
            db.add(WatchlistItem(user_id=current_user.id, media_id=media.id))
            await db.flush()
    except IntegrityError:
        # Double-tap race lost against the unique (user_id, media_id)
        # constraint - the row is there, so report it as present.
        await db.rollback()
        return {"status": "ok", "in_watchlist": True}
    await db.commit()
    return {"status": "ok", "in_watchlist": True}


@router.delete("")
async def remove_from_watchlist(
    media_type: str = Query(...),
    tmdb_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    try:
        mtype = MediaType(media_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid media_type")

    media = await _find_media(db, mtype, tmdb_id)
    if media is not None:
        await db.execute(
            delete(WatchlistItem).where(
                WatchlistItem.user_id == current_user.id,
                WatchlistItem.media_id == media.id,
            )
        )
        await db.commit()
    return {"status": "ok", "in_watchlist": False}
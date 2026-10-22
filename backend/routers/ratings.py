from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, or_, and_
from sqlalchemy.orm import aliased

from db import get_db
from models.media import Media
from models.ratings import Rating
from models.base import MediaType
from models.users import UserSettings
from core.friends import friend_ids
from core.notifications import notify_friends_of_rating
from models.profile import UserProfileData, PrivacyLevel
from dependencies import get_current_user, get_current_user_or_api_key
from models.users import User
from models.follows import Follow
from core.enrichment import enrich_media, create_media_safely
from core.identity import find_media, coerce_id
from core.episode_order import validate_episode_order, normalize_order_key, is_aired_order

router = APIRouter()


class RatingIn(BaseModel):
    # Any one of media_id / tmdb_id / tvdb_id identifies the item (a
    # TVDB-only episode has no tmdb_id - see core/identity.py).
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    media_id: Optional[int] = None
    media_type: str
    rating: float = Field(..., ge=0.0, le=10.0)
    review: Optional[str] = None
    season_number: Optional[int] = None
    episode_order: Optional[str] = None
    # Needed to create a not-yet-known episode (media_type "episode"), together with season_number.
    series_tmdb_id: Optional[int] = None
    episode_number: Optional[int] = None



def format_rating(rating: Rating, media: Media) -> dict:
    return {
        "id": rating.id,
        "media": {
            "id": media.id,
            "tmdb_id": media.tmdb_id,
            "tvdb_id": media.tvdb_id,
            "imdb_id": media.imdb_id,
            "type": media.media_type,
            "title": media.title,
            "poster_path": media.poster_path,
            "release_date": media.release_date,
        },
        "season_number": rating.season_number,
        "episode_order": rating.episode_order,
        "user_id": rating.user_id,
        "rating": rating.rating,
        "review": rating.review,
        "rated_at": rating.rated_at.isoformat(),
    }


@router.delete("/all")
async def clear_all_ratings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    await db.execute(delete(Rating).where(Rating.user_id == current_user.id))
    await db.commit()
    return {"status": "ok"}


@router.post("")
async def submit_rating(
    body: RatingIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    try:
        media_type = MediaType(body.media_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid media_type: {body.media_type}")

    # Look up existing Media row, create on-the-fly if missing
    media = await find_media(
        db, media_type, media_id=body.media_id, tmdb_id=body.tmdb_id, tvdb_id=body.tvdb_id,
    )

    if not media and not body.tmdb_id and body.tvdb_id and media_type == MediaType.series:
        # A TheTVDB-only show has no TMDB record - its series row is built
        # from the local Show instead.
        from core.enrichment import get_or_create_tvdb_series_media
        media = await get_or_create_tvdb_series_media(db, body.tvdb_id)
        if media is None:
            raise HTTPException(status_code=404, detail="Show not found locally; open its show page first so it can be created from TheTVDB")

    if not media and not body.tmdb_id:
        raise HTTPException(status_code=404, detail="Media not found")
    if not media:
        from routers.media import get_user_tmdb_key
        from core import tmdb
        api_key = await get_user_tmdb_key(db, current_user.id)
        try:
            if media_type == MediaType.movie:
                data = await tmdb.get_movie(body.tmdb_id, api_key=api_key)
                title = data.get("title")
            elif media_type == MediaType.series:
                title = None  # enrich_media will populate all fields including title
            else:
                if not body.series_tmdb_id or body.season_number is None or body.episode_number is None:
                    raise HTTPException(
                        status_code=400,
                        detail="series_tmdb_id, season_number and episode_number are required to rate a new episode",
                    )
                from core.enrichment import get_or_create_show_by_tmdb, enrich_media_safely
                show = await get_or_create_show_by_tmdb(db, body.series_tmdb_id, api_key)
                ep_data = await tmdb.get_episode(
                    body.series_tmdb_id, body.season_number, body.episode_number, api_key=api_key
                )
                media, _created = await create_media_safely(
                    db,
                    body.tmdb_id,
                    MediaType.episode,
                    title=ep_data.get("name", ""),
                    season_number=body.season_number,
                    episode_number=body.episode_number,
                    show_id=show.id,
                )
                media = await enrich_media_safely(db, media, api_key=api_key, series_tmdb_id=body.series_tmdb_id)
            if media_type != MediaType.episode:
                media, _created = await create_media_safely(db, body.tmdb_id, media_type, title=title or "")
                await enrich_media(media, api_key=api_key)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"TMDB Media not found: {e}")

    effective_season = None if media_type == MediaType.episode else body.season_number
    # A season rating carries the ordering it was made under (#174) so
    # "Season 3" of DVD order and of aired order stay distinct. NULL = aired.
    effective_episode_order = None
    if media_type == MediaType.series and effective_season is not None and body.episode_order:
        try:
            key = validate_episode_order(body.episode_order)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid episode order")
        effective_episode_order = None if is_aired_order(key) else key

    result2 = await db.execute(
        select(Rating).where(
            Rating.media_id == media.id,
            Rating.user_id == current_user.id,
            Rating.season_number == effective_season,
            Rating.episode_order == effective_episode_order,
        )
    )
    rating = result2.scalar_one_or_none()

    if rating:
        rating.rating = body.rating
        rating.review = body.review
        rating.rated_at = datetime.utcnow()
    else:
        rating = Rating(
            media_id=media.id,
            user_id=current_user.id,
            rating=body.rating,
            review=body.review,
            season_number=effective_season,
            episode_order=effective_episode_order,
        )
        db.add(rating)
        await notify_friends_of_rating(db, current_user.id, media, body.rating, effective_season)

    await db.commit()
    await db.refresh(rating)
    # A rating made under a non-aired ordering isn't pushed to external
    # services - they'd misread the season number (same rule as the
    # Rating.episode_order.is_(None) push filters in trakt/simkl/mdblist).
    if effective_episode_order is not None:
        return format_rating(rating, media)

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings = settings_result.scalar_one_or_none()
    from routers.sync import _fan_out_changes_to_other_connections

    await _fan_out_changes_to_other_connections(
        db,
        current_user.id,
        None,
        set(),
        {(media.id, effective_season): body.rating},
        settings=settings,
    )

    return format_rating(rating, media)


@router.get("")
async def get_ratings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    result = await db.execute(
        select(Rating, Media)
        .join(Media, Media.id == Rating.media_id)
        .where(Rating.user_id == current_user.id)
        .order_by(desc(Rating.rated_at))
    )
    return {"results": [format_rating(r, m) for r, m in result.all()]}


@router.get("/friends")
async def get_friends_ratings(
    media_type: str,
    tmdb_id: Optional[int] = Query(None),
    tvdb_id: Optional[int] = Query(None),
    media_id: Optional[int] = Query(None),
    season_number: Optional[int] = Query(None),
    episode_number: Optional[int] = Query(None),
    episode_order: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    try:
        mt = MediaType(media_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid media_type: {media_type}")

    tmdb = coerce_id(tmdb_id)
    tvdb = coerce_id(tvdb_id)
    med_id = coerce_id(media_id)
    if not (tmdb or tvdb or med_id):
        raise HTTPException(status_code=400, detail="One of tmdb_id, tvdb_id or media_id is required")

    media = await find_media(db, mt, media_id=med_id, tmdb_id=tmdb, tvdb_id=tvdb)
    if not media:
        return {"ratings": []}

    friends_subq = await friend_ids(db, current_user.id)
    friend_set = set(friends_subq)

    effective_season = None if mt == MediaType.episode else season_number
    effective_episode_order = None
    if mt == MediaType.series and effective_season is not None and episode_order:
        key = normalize_order_key(episode_order)
        effective_episode_order = None if is_aired_order(key) else key

    stmt = (
        select(Rating, User, UserProfileData)
        .join(User, Rating.user_id == User.id)
        .outerjoin(UserProfileData, User.id == UserProfileData.user_id)
        .where(
            Rating.media_id == media.id,
            or_(
                Rating.user_id.in_(friends_subq),
                and_(
                    Rating.user_id.in_(select(Follow.following_id).where(Follow.follower_id == current_user.id)),
                    UserProfileData.privacy_level == PrivacyLevel.public,
                ),
            ),
            Rating.season_number == effective_season if effective_season is not None else Rating.season_number.is_(None),
        )
    )

    if effective_episode_order is not None:
        stmt = stmt.where(Rating.episode_order == effective_episode_order)
    elif mt == MediaType.series and effective_season is not None:
        stmt = stmt.where(Rating.episode_order.is_(None))

    if current_user.role != "admin":
        stmt = stmt.where(
            UserProfileData.privacy_level.in_([PrivacyLevel.public, PrivacyLevel.friends_only])
        )

    stmt = stmt.order_by(desc(Rating.rated_at))
    result = await db.execute(stmt)
    rows = result.all()

    ratings_list = []
    for r, u, p in rows:
        display_name = p.display_name if p and p.display_name else u.username
        avatar_url = f"/profile/avatar/{u.id}" if p and p.avatar_path else None
        ratings_list.append({
            "id": r.id,
            "user_id": u.id,
            "username": u.username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "rating": r.rating,
            "review": r.review,
            "season_number": r.season_number,
            "episode_order": r.episode_order,
            "rated_at": r.rated_at.isoformat(),
            "is_friend": u.id in friend_set,
        })

    return {"ratings": ratings_list}


@router.get("/{media_id}")
async def get_media_rating(
    media_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    result = await db.execute(
        select(Rating, Media)
        .join(Media, Media.id == Rating.media_id)
        .where(Rating.media_id == media_id, Rating.user_id == current_user.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Rating not found")
    return format_rating(row[0], row[1])


@router.delete("")
async def delete_rating(
    media_type: str,
    tmdb_id: Optional[int] = Query(None),
    tvdb_id: Optional[int] = Query(None),
    media_id: Optional[int] = Query(None),
    season_number: Optional[int] = Query(None),
    episode_order: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    try:
        mt = MediaType(media_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid media_type: {media_type}")
    if not (tmdb_id or tvdb_id or media_id):
        raise HTTPException(status_code=400, detail="One of tmdb_id, tvdb_id or media_id is required")

    media = await find_media(db, mt, media_id=media_id, tmdb_id=tmdb_id, tvdb_id=tvdb_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    effective_season = None if mt == MediaType.episode else season_number
    effective_episode_order = None
    if mt == MediaType.series and effective_season is not None and episode_order:
        key = normalize_order_key(episode_order)
        effective_episode_order = None if is_aired_order(key) else key

    result = await db.execute(
        select(Rating).where(
            Rating.media_id == media.id,
            Rating.user_id == current_user.id,
            Rating.season_number == effective_season,
            Rating.episode_order == effective_episode_order,
        )
    )
    rating = result.scalar_one_or_none()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    await db.delete(rating)
    await db.commit()
    if effective_episode_order is not None:
        return {"status": "deleted"}

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    settings = settings_result.scalar_one_or_none()
    from routers.sync import _fan_out_changes_to_other_connections

    await _fan_out_changes_to_other_connections(
        db,
        current_user.id,
        None,
        set(),
        {},
        settings=settings,
        removed_ratings={(media.id, effective_season)},
    )

    return {"status": "deleted"}

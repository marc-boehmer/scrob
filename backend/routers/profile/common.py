from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from core.translations import get_media_translations, get_show_translations, get_user_metadata_language
from models.users import User
from models.profile import UserProfileData, PrivacyLevel
from models.events import WatchEvent
from models.media import Media
from models.follows import Follow
from models.global_settings import GlobalSettings
from core.friends import are_friends


async def _load_profile_access(user_id: int, current_user, db: AsyncSession):
    """Returns (user, profile, has_full_access) or raises 404/403."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_result = await db.execute(select(UserProfileData).where(UserProfileData.user_id == user_id))
    profile = profile_result.scalar_one_or_none()

    is_owner = current_user and current_user.id == user_id
    is_admin = current_user and current_user.role == "admin"
    privacy = profile.privacy_level if profile else PrivacyLevel.friends_only

    is_friend = False
    if current_user and not is_owner and privacy == PrivacyLevel.friends_only:
        is_friend = await are_friends(db, current_user.id, user_id)

    has_full_access = is_owner or is_admin or privacy == PrivacyLevel.public or is_friend

    # Do not let anonymous or invalid-API-key requests bypass the global
    # logged-out navigation setting, including requests for limited profiles.
    if not current_user:
        gs_result = await db.execute(select(GlobalSettings).where(GlobalSettings.id == 1))
        gs = gs_result.scalar_one_or_none()
        if not (gs and gs.enable_logged_out_navigation):
            raise HTTPException(status_code=403, detail="This profile is private")

    return user, profile, has_full_access


async def _check_profile_access(user_id: int, current_user, db: AsyncSession):
    user, profile, has_full_access = await _load_profile_access(user_id, current_user, db)
    if not has_full_access:
        raise HTTPException(status_code=403, detail="This profile is private")
    return user, profile


def _latest_episode_per_show_subquery(user_id: int):
    """One row per show: the id of that show's single most-recently-watched
    episode. DISTINCT ON (show_id) picks it (Postgres requires the leading
    ORDER BY to match the DISTINCT ON expression); callers re-sort the joined
    rows by watched_at themselves to rank shows by recency."""
    return (
        select(WatchEvent.id.label("we_id"))
        .distinct(Media.show_id)
        .join(Media, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == user_id,
            WatchEvent.completed == True,
            Media.media_type == "episode",
            WatchEvent.watched_at.isnot(None),
            Media.show_id.isnot(None),
        )
        .order_by(Media.show_id, WatchEvent.watched_at.desc())
    ).subquery()


async def _apply_viewer_language(db: AsyncSession, viewer, rows: list[tuple[dict, "Media", "ShowModel | None"]]) -> None:
    """Translate titles in profile listings into the viewer's Metadata Language
    (#460). Movies and episodes translate via MediaTranslation on their own
    media id; a show (or the show name beside an episode) via ShowTranslation.
    Anonymous viewers have no language, so they see the stored titles."""
    if not viewer or not rows:
        return
    lang = await get_user_metadata_language(db, viewer.id)
    if not lang:
        return
    media_ids = [m.id for item, m, _s in rows if item["media_type"] != "series"]
    show_ids = {s.id for _i, _m, s in rows if s}
    media_t = await get_media_translations(db, media_ids, lang)
    show_t = await get_show_translations(db, list(show_ids), lang)
    for item, media, show in rows:
        st = show_t.get(show.id) if show else None
        if item["media_type"] == "series":
            if st and st.get("title"):
                item["title"] = st["title"]
            continue
        mt = media_t.get(media.id)
        if mt and mt.get("title"):
            item["title"] = mt["title"]
        if st and st.get("title") and item.get("show_title"):
            item["show_title"] = st["title"]

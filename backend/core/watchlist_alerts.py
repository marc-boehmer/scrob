import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.global_settings import GlobalSettings
from models.media import Media
from models.notification import Notification
from models.profile import UserProfileData
from models.users import User, UserSettings
from models.watchlist import WatchlistItem
from models.watchlist_alert import WatchlistAlertState

logger = logging.getLogger("watchlist_alerts")

WATCHLIST_RELEASE = "watchlist_release"
WATCHLIST_STREAMING = "watchlist_streaming"


def release_date_due(release_date: str | None, added_at: datetime, today: date) -> date | None:
    if not release_date:
        return None
    try:
        release_day = date.fromisoformat(release_date[:10])
    except ValueError:
        return None
    if added_at.date() <= release_day <= today:
        return release_day
    return None


def streaming_providers(
    response: dict, country: str, selected_provider_ids: set[int]
) -> dict[int, str]:
    region = (response.get("results") or {}).get(country, {})
    providers: dict[int, str] = {}
    for provider in region.get("flatrate", []):
        provider_id = provider.get("provider_id")
        name = provider.get("provider_name")
        if provider_id is None or not name:
            continue
        try:
            provider_id = int(provider_id)
        except (TypeError, ValueError):
            continue
        if selected_provider_ids and provider_id not in selected_provider_ids:
            continue
        providers[provider_id] = str(name)
    return providers


async def send_watchlist_alerts(db: AsyncSession, today: date | None = None) -> int:
    from core.email import email_enabled, send_watchlist_alert_email
    from core import tmdb
    from models.base import MediaType

    mail_available = email_enabled()
    today = today or datetime.now(timezone.utc).date()
    rows = (await db.execute(
        select(WatchlistItem, Media, User, UserSettings, UserProfileData)
        .join(Media, Media.id == WatchlistItem.media_id)
        .join(User, User.id == WatchlistItem.user_id)
        .outerjoin(UserSettings, UserSettings.user_id == User.id)
        .outerjoin(UserProfileData, UserProfileData.user_id == User.id)
        .where(
            UserSettings.user_id.is_(None)
            | UserSettings.email_watchlist_release_dates.is_(True)
            | UserSettings.email_watchlist_streaming.is_(True),
            Media.media_type.in_([MediaType.movie, MediaType.series]),
            Media.tmdb_id.is_not(None),
        )
    )).all()
    global_tmdb_key = (await db.execute(
        select(GlobalSettings.tmdb_api_key).order_by(GlobalSettings.id).limit(1)
    )).scalar_one_or_none()

    sent = 0
    for watchlist_item, media, user, user_settings, profile in rows:
        release_alerts_enabled = user_settings is None or user_settings.email_watchlist_release_dates
        streaming_alerts_enabled = user_settings is None or user_settings.email_watchlist_streaming
        state = await db.get(WatchlistAlertState, watchlist_item.id)
        if state is None:
            state = WatchlistAlertState(watchlist_item_id=watchlist_item.id)
            db.add(state)
            await db.flush()

        events: list[tuple[str, str]] = []
        release_pending = False
        release_day = release_date_due(media.release_date, watchlist_item.added_at, today)
        if state.release_notified_at is None and media.release_date:
            try:
                release_is_past = date.fromisoformat(media.release_date[:10]) <= today
            except ValueError:
                release_is_past = False
            if release_is_past:
                if release_day and release_alerts_enabled:
                    events.append((
                        WATCHLIST_RELEASE,
                        f"Theatrical release date reached: {release_day.strftime('%B')} "
                        f"{release_day.day}, {release_day.year}",
                    ))
                    release_pending = True
                else:
                    state.release_notified_at = datetime.now(timezone.utc).replace(tzinfo=None)

        provider_ids: list[int] | None = None
        country = ((profile.country if profile and profile.country else "US").upper())[:2]
        if streaming_alerts_enabled:
            api_key = (user_settings.tmdb_api_key if user_settings else None) or global_tmdb_key
            if not api_key:
                logger.info("Streaming alert check skipped for user %s: no TMDB API key", user.id)
            else:
                selected_ids: set[int] = set()
                for value in (profile.streaming_services if profile else None) or []:
                    try:
                        selected_ids.add(int(value))
                    except (TypeError, ValueError):
                        continue
                try:
                    if media.media_type == MediaType.movie:
                        provider_response = await tmdb.get_movie_watch_providers(media.tmdb_id, api_key=api_key)
                    else:
                        provider_response = await tmdb.get_show_watch_providers(media.tmdb_id, api_key=api_key)
                    current_providers = streaming_providers(provider_response, country, selected_ids)
                    current_ids = sorted(current_providers)
                    if state.streaming_provider_ids is not None and state.streaming_country == country:
                        added_ids = set(current_ids) - set(state.streaming_provider_ids)
                        if added_ids:
                            names = sorted(current_providers[provider_id] for provider_id in added_ids)
                            events.append((WATCHLIST_STREAMING, f"Now available to stream on {', '.join(names)}"))
                    provider_ids = current_ids
                except Exception:
                    logger.exception(
                        "Could not check streaming providers for watchlist item %s (user %s)",
                        watchlist_item.id,
                        user.id,
                    )

        if events:
            link_type = "movie" if media.media_type == MediaType.movie else "show"
            link = f"/{link_type}/{media.tmdb_id}"
            for event_type, text in events:
                db.add(Notification(
                    user_id=user.id,
                    actor_id=None,
                    type=event_type,
                    shared_media_title=media.title[:500],
                    shared_media_link=link,
                    shared_comment=text,
                ))
            if release_pending:
                state.release_notified_at = datetime.now(timezone.utc).replace(tzinfo=None)
            sent += 1
        if provider_ids is not None:
            state.streaming_provider_ids = provider_ids
            state.streaming_country = country
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Could not save watchlist alert state for item %s (user %s)",
                watchlist_item.id,
                user.id,
            )
            raise
        if events and mail_available and user.email_confirmed:
            try:
                await send_watchlist_alert_email(user.email, media.title, link, [text for _, text in events])
            except Exception:
                logger.exception(
                    "Could not send watchlist alert for item %s (user %s)",
                    watchlist_item.id,
                    user.id,
                )

    return sent

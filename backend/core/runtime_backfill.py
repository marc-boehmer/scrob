"""One-time backfill of missing runtimes for watched movies and episodes.

Watch-time stats read the stored runtime, but older rows (or rows enriched
while TMDB returned 0) never got one. Once every watched movie has a runtime
this finds nothing and is a no-op on later startups."""

import asyncio
import logging

from sqlalchemy import func, select

from core import tmdb
from core.media_runtime import effective_runtime_expression
from models.events import WatchEvent
from models.media import Media, MediaType
from models.show import Show

log = logging.getLogger("uvicorn.error")

CONCURRENCY = 5


async def backfill_watched_movie_runtimes(session_factory) -> int:
    from routers.media import get_user_tmdb_key

    async with session_factory() as db:
        rows = (await db.execute(
            select(Media.id, Media.tmdb_id, func.min(WatchEvent.user_id))
            .select_from(Media)
            .join(WatchEvent, WatchEvent.media_id == Media.id)
            .where(
                Media.media_type == MediaType.movie,
                Media.tmdb_id.is_not(None),
                func.coalesce(effective_runtime_expression(), 0) <= 0,
            )
            .group_by(Media.id, Media.tmdb_id)
        )).all()
        if not rows:
            return 0

        keys = {uid: await get_user_tmdb_key(db, uid) for uid in {r[2] for r in rows}}

    sem = asyncio.Semaphore(CONCURRENCY)

    async def fetch(media_id, tmdb_id, user_id):
        async with sem:
            try:
                data = await tmdb.get_movie_light(tmdb_id, api_key=keys[user_id])
            except Exception as e:
                log.warning("Runtime backfill: TMDB fetch failed for movie %s: %s", tmdb_id, e)
                return None
        runtime = data.get("runtime")
        if isinstance(runtime, int) and runtime > 0:
            return media_id, runtime
        return None

    results = [r for r in await asyncio.gather(*(fetch(*r) for r in rows)) if r]
    if not results:
        return 0

    async with session_factory() as db:
        for media_id, runtime in results:
            media = await db.get(Media, media_id)
            if media and not media.runtime:
                media.runtime = runtime
        await db.commit()
    log.info("Runtime backfill: filled %d of %d watched movies", len(results), len(rows))
    return len(results)


async def backfill_watched_episode_runtimes(session_factory) -> int:
    """Fill watched episodes lacking a runtime from their TMDB season listing,
    falling back to that season's average episode length."""
    from routers.media import get_user_tmdb_key

    async with session_factory() as db:
        rows = (await db.execute(
            select(Media.id, Show.tmdb_id, Media.season_number, Media.episode_number, func.min(WatchEvent.user_id))
            .select_from(Media)
            .join(WatchEvent, WatchEvent.media_id == Media.id)
            .join(Show, Show.id == Media.show_id)
            .where(
                Media.media_type == MediaType.episode,
                Show.tmdb_id.is_not(None),
                Media.season_number.is_not(None),
                func.coalesce(effective_runtime_expression(), 0) <= 0,
            )
            .group_by(Media.id, Show.tmdb_id, Media.season_number, Media.episode_number)
        )).all()
        if not rows:
            return 0
        keys = {uid: await get_user_tmdb_key(db, uid) for uid in {r[4] for r in rows}}

    seasons: dict[tuple[int, int], int] = {}
    for _, show_tmdb_id, season, _, user_id in rows:
        seasons.setdefault((show_tmdb_id, season), user_id)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def fetch(key, user_id):
        async with sem:
            try:
                data = await tmdb.get_season(key[0], key[1], api_key=keys[user_id])
            except Exception as e:
                log.warning("Runtime backfill: TMDB season fetch failed for %s: %s", key, e)
                return key, {}, None
        by_episode = {
            ep.get("episode_number"): ep["runtime"]
            for ep in data.get("episodes", [])
            if isinstance(ep.get("runtime"), int) and ep["runtime"] > 0
        }
        average = round(sum(by_episode.values()) / len(by_episode)) if by_episode else None
        return key, by_episode, average

    fetched = {key: (eps, avg) for key, eps, avg in await asyncio.gather(
        *(fetch(k, u) for k, u in seasons.items())
    )}

    updates = []
    for media_id, show_tmdb_id, season, episode, _ in rows:
        eps, avg = fetched[(show_tmdb_id, season)]
        runtime = eps.get(episode) or avg
        if runtime:
            updates.append((media_id, runtime))
    if not updates:
        return 0

    async with session_factory() as db:
        for media_id, runtime in updates:
            media = await db.get(Media, media_id)
            if media and not media.runtime:
                media.runtime = runtime
        await db.commit()
    log.info("Runtime backfill: filled %d of %d watched episodes", len(updates), len(rows))
    return len(updates)


async def run_runtime_backfill(session_factory) -> None:
    await asyncio.sleep(60)
    try:
        await backfill_watched_movie_runtimes(session_factory)
        await backfill_watched_episode_runtimes(session_factory)
    except Exception as e:
        log.warning("Runtime backfill failed: %s", e)

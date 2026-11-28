import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from core.watch_stats import WatchStats, get_watch_stats


def db_returning(row):
    result = MagicMock()
    result.one.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


class GetWatchStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_last_watched_at_as_iso_string(self):
        # Arrange
        db = db_returning((3, 90, datetime(2026, 10, 12, 21, 5)))

        # Act
        stats = await get_watch_stats(db, 1, show_id=7)

        # Assert
        self.assertEqual(stats, WatchStats(3, 90, "2026-10-12T21:05:00"))

    async def test_last_watched_at_is_none_without_dated_completed_plays(self):
        # Arrange
        db = db_returning((2, 0, None))

        # Act
        stats = await get_watch_stats(db, 1, tmdb_id=5, media_type="movie")

        # Assert
        self.assertIsNone(stats.last_watched_at)

    async def test_empty_media_ids_skips_the_query(self):
        # Arrange
        db = db_returning(None)

        # Act
        stats = await get_watch_stats(db, 1, media_ids=[])

        # Assert
        self.assertEqual(stats, WatchStats(0, 0, None))
        db.execute.assert_not_called()

    def test_query_filters_last_watched_to_completed_plays(self):
        # Arrange
        from sqlalchemy.dialects import postgresql
        import core.watch_stats as ws
        captured = {}

        async def capture(query):
            captured["sql"] = str(query.compile(dialect=postgresql.dialect()))
            result = MagicMock()
            result.one.return_value = (0, 0, None)
            return result

        db = MagicMock()
        db.execute = capture

        # Act
        import asyncio
        asyncio.run(ws.get_watch_stats(db, 1, show_id=7))

        # Assert
        self.assertIn("max(CASE WHEN (watch_events.completed = true) THEN watch_events.watched_at END)", captured["sql"])


class WatchStatsOnRealRowsTests(unittest.IsolatedAsyncioTestCase):
    """The counting runs in SQL, so check it against real rows."""

    async def asyncSetUp(self):
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.pool import StaticPool
        from models.base import Base

        compiles(JSONB, "sqlite")(lambda type_, compiler, **kw: "JSON")
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.addAsyncCleanup(self.engine.dispose)

    async def test_in_progress_events_are_not_plays(self):
        from models.events import WatchEvent
        from models.media import Media, MediaType

        async with self.Session() as db:
            db.add_all([
                Media(id=1, tmdb_id=11, media_type=MediaType.episode, title="E1", show_id=7, season_number=1, episode_number=1, runtime=40),
                Media(id=2, tmdb_id=12, media_type=MediaType.episode, title="E2", show_id=7, season_number=1, episode_number=2, runtime=40),
            ])
            await db.commit()
            db.add_all([
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 1, 1), completed=True),
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 2, 1), completed=True),
                WatchEvent(user_id=1, media_id=2, watched_at=datetime(2026, 3, 1), completed=False),
                WatchEvent(user_id=2, media_id=1, watched_at=datetime(2026, 4, 1), completed=True),
            ])
            await db.commit()

            stats = await get_watch_stats(db, 1, show_id=7)

        # Two completed plays of E1 only: the in-progress E2 and the other user's play do not count.
        self.assertEqual(stats, WatchStats(2, 80, "2026-02-01T00:00:00"))

    async def test_a_pulled_play_count_counts_as_that_many_plays(self):
        # #567: Jellyfin reports PlayCount 3; the pull stores one event with play_count=3.
        from models.events import WatchEvent
        from models.media import Media, MediaType

        async with self.Session() as db:
            db.add(Media(id=1, tmdb_id=11, media_type=MediaType.episode, title="E1", show_id=7, season_number=1, episode_number=1, runtime=40))
            await db.commit()
            db.add_all([
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 1, 1), completed=True, play_count=3),
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 2, 1), completed=True, play_count=1),
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 3, 1), completed=False, play_count=5),
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 4, 1), completed=True, play_count=0),
            ])
            await db.commit()

            stats = await get_watch_stats(db, 1, show_id=7)

        # 3 + 1 + max(0, 1) completed plays; the in-progress row is ignored.
        self.assertEqual(stats, WatchStats(5, 200, "2026-04-01T00:00:00"))

    async def test_string_runtime_fallback_is_counted_for_each_play(self):
        from models.events import WatchEvent
        from models.media import Media, MediaType

        async with self.Session() as db:
            db.add(Media(
                id=1, tmdb_id=11, media_type=MediaType.movie, title="Movie",
                runtime=None, tmdb_data={"runtime": "120"},
            ))
            await db.commit()
            db.add(WatchEvent(
                user_id=1, media_id=1, watched_at=datetime(2026, 5, 1),
                completed=True, play_count=3,
            ))
            await db.commit()

            stats = await get_watch_stats(db, 1, tmdb_id=11, media_type="movie")

        self.assertEqual(stats, WatchStats(3, 360, "2026-05-01T00:00:00"))

    async def test_zero_runtime_column_falls_back_to_tmdb_data(self):
        from models.events import WatchEvent
        from models.media import Media, MediaType

        async with self.Session() as db:
            db.add(Media(
                id=1, tmdb_id=11, media_type=MediaType.movie, title="Movie",
                runtime=0, tmdb_data={"runtime": 100},
            ))
            await db.commit()
            db.add(WatchEvent(
                user_id=1, media_id=1, watched_at=datetime(2026, 5, 1),
                completed=True, play_count=1,
            ))
            await db.commit()

            stats = await get_watch_stats(db, 1, tmdb_id=11, media_type="movie")

        self.assertEqual(stats.watch_time_minutes, 100)

    async def test_backfill_fills_runtime_of_watched_movies_only(self):
        import sys
        import types
        from unittest.mock import patch
        from models.events import WatchEvent
        from models.media import Media, MediaType

        async with self.Session() as db:
            db.add_all([
                Media(id=1, tmdb_id=11, media_type=MediaType.movie, title="Zero", runtime=0),
                Media(id=2, tmdb_id=12, media_type=MediaType.movie, title="Unwatched"),
                Media(id=3, tmdb_id=13, media_type=MediaType.movie, title="Fine", runtime=90),
            ])
            await db.commit()
            db.add_all([
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 5, 1), completed=True),
                WatchEvent(user_id=1, media_id=3, watched_at=datetime(2026, 5, 2), completed=True),
            ])
            await db.commit()

        fake_router = types.ModuleType("routers.media")
        fake_router.get_user_tmdb_key = AsyncMock(return_value="key")
        from core import runtime_backfill

        with patch.dict(sys.modules, {"routers.media": fake_router}), \
                patch.object(runtime_backfill.tmdb, "get_movie_light", AsyncMock(return_value={"runtime": 101})) as fetch:
            filled = await runtime_backfill.backfill_watched_movie_runtimes(self.Session)

        self.assertEqual(filled, 1)
        fetch.assert_awaited_once()
        async with self.Session() as db:
            self.assertEqual((await db.get(Media, 1)).runtime, 101)
            self.assertIsNone((await db.get(Media, 2)).runtime)

    async def test_backfill_fills_watched_episode_runtimes_with_season_average(self):
        import sys
        import types
        from unittest.mock import patch
        from models.events import WatchEvent
        from models.media import Media, MediaType
        from models.show import Show

        async with self.Session() as db:
            db.add(Show(id=7, tmdb_id=700, title="Show"))
            await db.commit()
            db.add_all([
                Media(id=1, tmdb_id=21, media_type=MediaType.episode, title="E1", show_id=7, season_number=1, episode_number=1),
                Media(id=2, tmdb_id=22, media_type=MediaType.episode, title="E2", show_id=7, season_number=1, episode_number=2),
            ])
            await db.commit()
            db.add_all([
                WatchEvent(user_id=1, media_id=1, watched_at=datetime(2026, 5, 1), completed=True),
                WatchEvent(user_id=1, media_id=2, watched_at=datetime(2026, 5, 2), completed=True),
            ])
            await db.commit()

        season = {"episodes": [
            {"episode_number": 1, "runtime": 40},
            {"episode_number": 3, "runtime": 50},
        ]}
        fake_router = types.ModuleType("routers.media")
        fake_router.get_user_tmdb_key = AsyncMock(return_value="key")
        from core import runtime_backfill

        with patch.dict(sys.modules, {"routers.media": fake_router}), \
                patch.object(runtime_backfill.tmdb, "get_season", AsyncMock(return_value=season)):
            filled = await runtime_backfill.backfill_watched_episode_runtimes(self.Session)

        self.assertEqual(filled, 2)
        async with self.Session() as db:
            self.assertEqual((await db.get(Media, 1)).runtime, 40)
            self.assertEqual((await db.get(Media, 2)).runtime, 45)

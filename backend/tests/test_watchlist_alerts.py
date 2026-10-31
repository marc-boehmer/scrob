import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from core.watchlist_alerts import release_date_due, send_watchlist_alerts, streaming_providers
from models.base import MediaType
from models.watchlist_alert import WatchlistAlertState


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Scalar:
    def scalar_one_or_none(self):
        return "global-tmdb-key"


class WatchlistAlertTests(unittest.IsolatedAsyncioTestCase):
    def test_release_date_only_notifies_after_watchlist_addition(self):
        today = date(2026, 10, 31)
        self.assertEqual(
            release_date_due("2026-10-31", datetime(2026, 10, 1), today),
            today,
        )
        self.assertIsNone(
            release_date_due("2026-09-30", datetime(2026, 10, 1), today)
        )
        self.assertIsNone(
            release_date_due("2026-11-01", datetime(2026, 10, 1), today)
        )

    def test_streaming_provider_snapshot_uses_profile_country_and_selection(self):
        response = {
            "results": {
                "US": {
                    "flatrate": [
                        {"provider_id": 8, "provider_name": "Provider A"},
                        {"provider_id": 9, "provider_name": "Provider B"},
                    ]
                },
                "GB": {"flatrate": [{"provider_id": 10, "provider_name": "Provider C"}]},
            }
        }
        self.assertEqual(streaming_providers(response, "US", {9}), {9: "Provider B"})
        self.assertEqual(streaming_providers(response, "GB", set()), {10: "Provider C"})

    async def test_sends_combined_release_and_new_streaming_email_once(self):
        state = WatchlistAlertState(
            watchlist_item_id=4,
            streaming_provider_ids=[8],
            streaming_country="US",
        )
        watchlist_item = SimpleNamespace(id=4, added_at=datetime(2026, 10, 1))
        media = SimpleNamespace(
            id=3,
            media_type=MediaType.movie,
            tmdb_id=123,
            title="Example Movie",
            release_date="2026-10-31",
        )
        user = SimpleNamespace(id=2, email="user@example.com", email_confirmed=True)
        user_settings = SimpleNamespace(
            tmdb_api_key=None,
            email_watchlist_release_dates=True,
            email_watchlist_streaming=True,
        )
        profile = SimpleNamespace(country="US", streaming_services=[])
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[_Rows([(watchlist_item, media, user, user_settings, profile)]), _Scalar()]),
            get=AsyncMock(return_value=state),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        provider_response = {
            "results": {
                "US": {
                    "flatrate": [
                        {"provider_id": 8, "provider_name": "Provider A"},
                        {"provider_id": 9, "provider_name": "Provider B"},
                    ]
                }
            }
        }
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_watchlist_alert_email", new_callable=AsyncMock) as send_email, \
             patch("core.tmdb.get_movie_watch_providers", new_callable=AsyncMock, return_value=provider_response):
            sent = await send_watchlist_alerts(db, today=date(2026, 10, 31))

        self.assertEqual(sent, 1)
        send_email.assert_awaited_once()
        events = send_email.await_args.args[3]
        self.assertEqual(
            events,
            [
                "Theatrical release date reached: October 31, 2026",
                "Now available to stream on Provider B",
            ],
        )
        self.assertEqual(state.streaming_provider_ids, [8, 9])
        self.assertIsNotNone(state.release_notified_at)
        db.commit.assert_awaited_once()
        notifications = [call.args[0] for call in db.add.call_args_list if hasattr(call.args[0], "shared_comment")]
        self.assertEqual(
            [(n.type, n.actor_id, n.shared_media_link) for n in notifications],
            [("watchlist_release", None, "/movie/123"), ("watchlist_streaming", None, "/movie/123")],
        )

        second_db = SimpleNamespace(
            execute=AsyncMock(side_effect=[_Rows([(watchlist_item, media, user, user_settings, profile)]), _Scalar()]),
            get=AsyncMock(return_value=state),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_watchlist_alert_email", new_callable=AsyncMock) as send_again, \
             patch("core.tmdb.get_movie_watch_providers", new_callable=AsyncMock, return_value=provider_response):
            sent_again = await send_watchlist_alerts(second_db, today=date(2026, 10, 31))

        self.assertEqual(sent_again, 0)
        send_again.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

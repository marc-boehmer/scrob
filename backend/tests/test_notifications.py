import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "******localhost/test")

from core.notifications import email_friend_media_share, notify_friends_of_rating
from models.base import MediaType
from models.notification import Notification
from models.profile import PrivacyLevel
from routers.notifications import MediaShareRequest, _notification_media, share_media


class _Scalar:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


def _db(privacy, followers=()):
    db = SimpleNamespace(add=Mock())
    db.execute = AsyncMock(side_effect=[_Scalar(privacy), _Rows(list(followers))])
    return db


class FriendRatingNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notifies_every_friend(self):
        db = _db(PrivacyLevel.friends_only)
        media = SimpleNamespace(id=9, media_type=MediaType.movie)
        with patch("core.notifications.friend_ids", AsyncMock(return_value=[2, 3])):
            await notify_friends_of_rating(db, 1, media, 8.5)
        added = [c.args[0] for c in db.add.call_args_list]
        self.assertEqual([n.user_id for n in added], [2, 3])
        self.assertTrue(all(n.type == "friend_rating" and n.actor_id == 1 and n.media_id == 9 and n.rating == 8.5 for n in added))

    async def test_followers_of_a_public_profile_are_notified_once(self):
        db = _db(PrivacyLevel.public, followers=[3, 4])
        media = SimpleNamespace(id=9, media_type=MediaType.movie)
        with patch("core.notifications.friend_ids", AsyncMock(return_value=[2, 3])):
            await notify_friends_of_rating(db, 1, media, 8)
        self.assertEqual([c.args[0].user_id for c in db.add.call_args_list], [2, 3, 4])

    async def test_followers_are_not_notified_for_friends_only_profiles(self):
        db = _db(PrivacyLevel.friends_only, followers=[4])
        media = SimpleNamespace(id=9, media_type=MediaType.movie)
        with patch("core.notifications.friend_ids", AsyncMock(return_value=[2])):
            await notify_friends_of_rating(db, 1, media, 8)
        self.assertEqual([c.args[0].user_id for c in db.add.call_args_list], [2])

    async def test_private_profile_notifies_nobody(self):
        db = _db(PrivacyLevel.private)
        media = SimpleNamespace(id=9, media_type=MediaType.series)
        with patch("core.notifications.friend_ids", AsyncMock(return_value=[2])):
            await notify_friends_of_rating(db, 1, media, 7)
        db.add.assert_not_called()

    async def test_season_and_episode_ratings_notify_too(self):
        db = _db(PrivacyLevel.public)
        db.execute.side_effect = [_Scalar(PrivacyLevel.public), _Rows([]), _Scalar(PrivacyLevel.public), _Rows([])]
        with patch("core.notifications.friend_ids", AsyncMock(return_value=[2])):
            await notify_friends_of_rating(db, 1, SimpleNamespace(id=9, media_type=MediaType.series), 7, 3)
            await notify_friends_of_rating(db, 1, SimpleNamespace(id=10, media_type=MediaType.episode), 6)
        season, episode = [c.args[0] for c in db.add.call_args_list]
        self.assertEqual((season.media_id, season.season_number), (9, 3))
        self.assertEqual((episode.media_id, episode.season_number), (10, None))


class MediaShareNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shares_to_selected_friends_with_canonical_movie_link(self):
        friends = [
            SimpleNamespace(requester_id=1, addressee_id=2),
            SimpleNamespace(requester_id=3, addressee_id=1),
        ]
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: friends))
        db = SimpleNamespace(execute=AsyncMock(return_value=result), add=Mock(), commit=AsyncMock())
        body = MediaShareRequest(
            recipient_ids=[2, 3], media_type="movie", tmdb_id=550, title=" Fight Club ",
        )

        with patch("routers.notifications.email_friend_media_share", AsyncMock()) as send_email:
            response = await share_media(body, SimpleNamespace(id=1), db)

        self.assertEqual(response, {"sent": 2})
        notifications = [call.args[0] for call in db.add.call_args_list]
        self.assertEqual([n.user_id for n in notifications], [2, 3])
        self.assertTrue(all(
            n.actor_id == 1
            and n.type == "friend_media_share"
            and n.shared_media_title == "Fight Club"
            and n.shared_media_link == "/media/movie/550"
            for n in notifications
        ))
        db.commit.assert_awaited_once()
        self.assertEqual(
            send_email.await_args_list,
            [
                call(db, 1, 2, "Fight Club", "/media/movie/550"),
                call(db, 1, 3, "Fight Club", "/media/movie/550"),
            ],
        )

    async def test_rejects_non_friend_recipient_without_sending(self):
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        db = SimpleNamespace(execute=AsyncMock(return_value=result), add=Mock(), commit=AsyncMock())
        body = MediaShareRequest(recipient_ids=[9], media_type="series", tvdb_id=81189, title="Example")

        with self.assertRaises(HTTPException) as raised:
            await share_media(body, SimpleNamespace(id=1), db)

        self.assertEqual(raised.exception.status_code, 403)
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_shares_tvdb_only_show(self):
        friends = [SimpleNamespace(requester_id=1, addressee_id=2)]
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: friends))
        db = SimpleNamespace(execute=AsyncMock(return_value=result), add=Mock(), commit=AsyncMock())
        body = MediaShareRequest(recipient_ids=[2], media_type="series", tvdb_id=81189, title="Example Show")

        with patch("routers.notifications.email_friend_media_share", AsyncMock()) as send_email:
            response = await share_media(body, SimpleNamespace(id=1), db)

        self.assertEqual(response, {"sent": 1})
        notification = db.add.call_args.args[0]
        self.assertEqual(notification.shared_media_link, "/show/tvdb/81189")
        send_email.assert_awaited_once_with(db, 1, 2, "Example Show", "/show/tvdb/81189")

    async def test_show_notification_contains_share_link(self):
        notification = Notification(
            type="friend_media_share",
            shared_media_title="Example Show",
            shared_media_link="/show/tvdb/81189",
        )

        self.assertEqual(
            _notification_media(notification, None),
            {
                "title": "Example Show",
                "type": "shared",
                "season_number": None,
                "episode_number": None,
                "link": "/show/tvdb/81189",
            },
        )

    def test_requires_media_identifier_and_unique_recipients(self):
        with self.assertRaises(ValueError):
            MediaShareRequest(recipient_ids=[2], media_type="series", title="Example")
        with self.assertRaises(ValueError):
            MediaShareRequest(recipient_ids=[2, 2], media_type="movie", tmdb_id=5, title="Example")


class EmailNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_friend_media_share_email_is_sent_to_confirmed_recipient(self):
        recipient = SimpleNamespace(email="a@x.io", email_confirmed=True)
        sender = SimpleNamespace(display_name="Bob")
        db = SimpleNamespace(
            get=AsyncMock(side_effect=[recipient, sender]),
            execute=AsyncMock(return_value=_Scalar(True)),
        )
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_friend_media_share_email", AsyncMock()) as send:
            await email_friend_media_share(db, 1, 2, "Example", "/show/123")
        send.assert_awaited_once_with("a@x.io", "Bob", "Example", "/show/123")

    async def test_friend_media_share_email_respects_opt_out(self):
        recipient = SimpleNamespace(email="a@x.io", email_confirmed=True)
        db = SimpleNamespace(
            get=AsyncMock(side_effect=[recipient, SimpleNamespace(display_name="Bob")]),
            execute=AsyncMock(return_value=_Scalar(False)),
        )
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_friend_media_share_email", AsyncMock()) as send:
            await email_friend_media_share(db, 1, 2, "Example", "/show/123")
        send.assert_not_awaited()

    async def test_friend_media_share_email_skipped_without_smtp(self):
        db = SimpleNamespace(get=AsyncMock())
        with patch("core.email.email_enabled", return_value=False):
            await email_friend_media_share(db, 1, 2, "Example", "/show/123")
        db.get.assert_not_awaited()

    async def test_friend_media_share_email_failure_is_swallowed(self):
        recipient = SimpleNamespace(email="a@x.io", email_confirmed=True)
        db = SimpleNamespace(
            get=AsyncMock(side_effect=[recipient, SimpleNamespace(display_name="Bob")]),
            execute=AsyncMock(return_value=_Scalar(True)),
        )
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_friend_media_share_email", AsyncMock(side_effect=OSError("down"))):
            await email_friend_media_share(db, 1, 2, "Example", "/show/123")

    async def test_friend_media_share_email_escapes_title_and_uses_media_link(self):
        from core.email import send_friend_media_share_email

        with patch("core.email.send_email", AsyncMock()) as send:
            await send_friend_media_share_email("a@x.io", "Bob & Co", "<Example>", "/media/movie/5")

        subject, body = send.await_args.args[1:]
        self.assertEqual(subject, "A friend shared a title with you on Scrob")
        self.assertIn("Bob &amp; Co", body)
        self.assertIn("&lt;Example&gt;", body)
        self.assertIn("/media/movie/5", body)

    async def test_friend_request_email_is_sent_to_confirmed_addressee(self):
        from core.notifications import email_friend_request
        addressee = SimpleNamespace(email="a@x.io", email_confirmed=True)
        requester = SimpleNamespace(display_name="Bob")
        db = SimpleNamespace(get=AsyncMock(side_effect=[addressee, requester]), execute=AsyncMock(return_value=_Scalar(None)))
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_friend_request_email", AsyncMock()) as send:
            await email_friend_request(db, 1, 2)
        send.assert_awaited_once_with("a@x.io", "Bob")

    async def test_friend_request_email_skipped_when_user_opted_out(self):
        from core.notifications import email_friend_request
        addressee = SimpleNamespace(email="a@x.io", email_confirmed=True)
        db = SimpleNamespace(get=AsyncMock(side_effect=[addressee, SimpleNamespace(display_name="Bob")]), execute=AsyncMock(return_value=_Scalar(False)))
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_friend_request_email", AsyncMock()) as send:
            await email_friend_request(db, 1, 2)
        send.assert_not_awaited()

    async def test_friend_request_email_skipped_without_smtp(self):
        from core.notifications import email_friend_request
        db = SimpleNamespace(get=AsyncMock())
        with patch("core.email.email_enabled", return_value=False):
            await email_friend_request(db, 1, 2)
        db.get.assert_not_called()

    async def test_friend_request_email_failure_is_swallowed(self):
        from core.notifications import email_friend_request
        db = SimpleNamespace(get=AsyncMock(side_effect=[SimpleNamespace(email="a@x.io", email_confirmed=True), SimpleNamespace(display_name="Bob")]), execute=AsyncMock(return_value=_Scalar(None)))
        with patch("core.email.email_enabled", return_value=True), \
             patch("core.email.send_friend_request_email", AsyncMock(side_effect=OSError("down"))):
            await email_friend_request(db, 1, 2)

    async def test_digest_skipped_without_smtp(self):
        from core.notifications import send_rating_digests
        db = SimpleNamespace(execute=AsyncMock())
        with patch("core.email.email_enabled", return_value=False):
            self.assertEqual(await send_rating_digests(db), 0)
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

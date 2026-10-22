import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")

from core.friends import status_for
from models.friendship import Friendship
from routers.friends import send_request


class _Result:
    def __init__(self, item=None):
        self.item = item

    def first(self):
        return self.item

    def scalars(self):
        return self


class _FakeSession:
    def __init__(self, results):
        self.execute = AsyncMock(side_effect=[_Result(item) for item in results])
        self.add = Mock()
        self.commit = AsyncMock()


class FriendRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_creates_pending_friendship(self):
        db = _FakeSession([(2,), None])
        response = await send_request(user_id=2, current_user=SimpleNamespace(id=1), db=db)
        self.assertEqual(response, {"status": "request_sent"})
        added = db.add.call_args.args[0]
        self.assertEqual((added.requester_id, added.addressee_id, added.status), (1, 2, "pending"))

    async def test_reciprocal_request_is_accepted(self):
        incoming = Friendship(requester_id=2, addressee_id=1, status="pending")
        db = _FakeSession([(2,), incoming])
        response = await send_request(user_id=2, current_user=SimpleNamespace(id=1), db=db)
        self.assertEqual(response, {"status": "friends"})
        self.assertEqual(incoming.status, "accepted")

    def test_status_is_relative_to_viewer(self):
        pending = Friendship(requester_id=1, addressee_id=2, status="pending")
        self.assertEqual(status_for(pending, 1), "request_sent")
        self.assertEqual(status_for(pending, 2), "request_received")
        self.assertEqual(status_for(None, 1), "none")


if __name__ == "__main__":
    unittest.main()

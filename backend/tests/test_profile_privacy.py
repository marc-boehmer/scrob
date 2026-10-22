import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")

from fastapi import HTTPException

from models.base import PrivacyLevel, UserRole
from models.profile import UserProfileData
from models.users import User
from routers.profile import follow_user, get_public_profile
from schemas import PublicProfileResponse


class _Result:
    def __init__(self, item=None):
        self.item = item

    def scalar_one_or_none(self):
        return self.item

    def scalars(self):
        return self

    def first(self):
        return self.item


class _FakeSession:
    def __init__(self, results):
        self.execute = AsyncMock(side_effect=[_Result(item) for item in results])
        self.add = Mock()
        self.commit = AsyncMock()


class ProfilePrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_profile_returns_only_identity_and_privacy(self):
        user = User(id=2, username="private-user", role=UserRole.user)
        profile = UserProfileData(
            user_id=2,
            display_name="Private Name",
            bio="Should not be visible",
            privacy_level=PrivacyLevel.private,
        )
        db = _FakeSession([user, profile, None, None])

        response = await get_public_profile(
            user_id=2,
            db=db,
            current_user=SimpleNamespace(id=1, role="user"),
        )

        serialized = PublicProfileResponse.model_validate(response).model_dump(
            mode="json", exclude_unset=True
        )
        self.assertEqual(
            serialized,
            {
                "id": 2,
                "display_name": "Private Name",
                "privacy_level": "private",
                "is_following": False,
                "friendship_status": "none",
                "is_limited": True,
            },
        )
        self.assertEqual(db.execute.await_count, 4)

    async def test_follow_rejects_private_profile(self):
        target = User(id=2, username="private-user", role=UserRole.user)
        profile = UserProfileData(user_id=2, privacy_level=PrivacyLevel.private)
        db = _FakeSession([target, profile])

        with self.assertRaises(HTTPException) as raised:
            await follow_user(user_id=2, current_user=SimpleNamespace(id=1), db=db)

        self.assertEqual(raised.exception.status_code, 403)
        db.add.assert_not_called()

    async def test_follow_allows_public_profile(self):
        target = User(id=2, username="public-user", role=UserRole.user)
        profile = UserProfileData(user_id=2, privacy_level=PrivacyLevel.public)
        db = _FakeSession([target, profile, None])

        response = await follow_user(user_id=2, current_user=SimpleNamespace(id=1), db=db)

        self.assertEqual(response, {"status": "following"})
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

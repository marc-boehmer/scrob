import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/test")

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from db import get_db
from dependencies import get_current_user
from models.email_activation import EmailActivation
from models.users import User
from routers import auth
from core.limiter import limiter


class EmailChangeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(User.__table__.create)
            await conn.run_sync(EmailActivation.__table__.create)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.Session() as db:
            db.add_all([
                User(id=1, email="alice@example.com", username="alice", api_key="alice-key"),
                User(id=2, email="taken@example.com", username="bob", api_key="bob-key"),
            ])
            await db.commit()

        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(auth.router, prefix="/auth")

        async def _override_db():
            async with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=1, email="alice@example.com"
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)
        self.addAsyncCleanup(self.engine.dispose)

    async def test_email_changes_only_after_confirmation(self):
        with (
            patch.object(auth.app_settings, "smtp_address", "smtp.example.com"),
            patch("routers.auth.send_activation_email", new_callable=AsyncMock) as send_email,
        ):
            response = await self.client.post(
                "/auth/change-email",
                json={"email": "  ALICE.NEW@example.com "},
            )

        self.assertEqual(response.status_code, 200, response.text)
        send_email.assert_awaited_once()
        args, kwargs = send_email.await_args
        self.assertEqual(args[0], "alice.new@example.com")
        self.assertTrue(kwargs["email_change"])

        async with self.Session() as db:
            user = await db.get(User, 1)
            activation = (
                await db.execute(select(EmailActivation).where(EmailActivation.user_id == 1))
            ).scalar_one()
            self.assertEqual(user.email, "alice@example.com")
            token = activation.token

        confirmed = await self.client.post(f"/auth/activate/{token}")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertTrue(confirmed.json()["email_changed"])

        async with self.Session() as db:
            user = await db.get(User, 1)
            self.assertEqual(user.email, "alice.new@example.com")
            self.assertTrue(user.email_confirmed)
            self.assertIsNone(
                (await db.execute(select(EmailActivation).where(EmailActivation.token == token)))
                .scalar_one_or_none()
            )

    async def test_existing_email_is_rejected(self):
        with patch.object(auth.app_settings, "smtp_address", "smtp.example.com"):
            response = await self.client.post(
                "/auth/change-email",
                json={"email": "TAKEN@example.com"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already in use", response.json()["detail"])

    async def test_change_requires_configured_smtp(self):
        with patch.object(auth.app_settings, "smtp_address", None):
            response = await self.client.post(
                "/auth/change-email",
                json={"email": "alice.new@example.com"},
            )

        self.assertEqual(response.status_code, 503)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.users import UserSettings


async def get_user_email_language(db: AsyncSession, user_id: int) -> str | None:
    return (await db.execute(
        select(UserSettings.ui_language).where(UserSettings.user_id == user_id)
    )).scalar_one_or_none()

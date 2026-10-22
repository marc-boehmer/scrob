from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.friends import friend_ids
from models.follows import Follow
from models.notification import Notification
from models.profile import PrivacyLevel, UserProfileData

FRIEND_REQUEST = "friend_request"
FRIEND_RATING = "friend_rating"


def notify_friend_request(db: AsyncSession, requester_id: int, addressee_id: int) -> None:
    db.add(Notification(user_id=addressee_id, actor_id=requester_id, type=FRIEND_REQUEST))


async def clear_friend_request(db: AsyncSession, requester_id: int, addressee_id: int) -> None:
    """Drop the request notification once the request is accepted, declined or cancelled."""
    await db.execute(
        delete(Notification).where(
            Notification.type == FRIEND_REQUEST,
            Notification.user_id == addressee_id,
            Notification.actor_id == requester_id,
        )
    )


async def notify_friends_of_rating(
    db: AsyncSession, user_id: int, media, rating: float | None, season_number: int | None = None
) -> None:
    """Tell the rater's friends - and, for a public profile, their followers - about a first-time rating."""
    privacy = (await db.execute(
        select(UserProfileData.privacy_level).where(UserProfileData.user_id == user_id)
    )).scalar_one_or_none()
    if privacy == PrivacyLevel.private:
        return
    recipients = set(await friend_ids(db, user_id))
    if privacy == PrivacyLevel.public:
        recipients.update((await db.execute(
            select(Follow.follower_id).where(Follow.following_id == user_id)
        )).scalars().all())
    for recipient_id in sorted(recipients):
        db.add(Notification(
            user_id=recipient_id, actor_id=user_id, type=FRIEND_RATING, media_id=media.id,
            season_number=season_number, rating=rating,
        ))

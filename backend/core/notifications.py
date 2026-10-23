import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.friends import friend_ids
from models.follows import Follow
from models.notification import Notification
from models.profile import PrivacyLevel, UserProfileData

logger = logging.getLogger("uvicorn.error")

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


async def email_friend_request(db: AsyncSession, requester_id: int, addressee_id: int) -> None:
    """Immediately email the addressee about a new friend request. Never raises."""
    from core.email import email_enabled, send_friend_request_email
    from models.users import User

    if not email_enabled():
        logger.info("Friend request email skipped: SMTP_ADDRESS is not configured")
        return
    try:
        addressee = await db.get(User, addressee_id)
        requester = await db.get(User, requester_id)
        if not addressee or not requester or not addressee.email_confirmed:
            logger.info("Friend request email skipped: addressee %s missing or email not confirmed", addressee_id)
            return
        logger.info("Sending friend request email to user %s", addressee_id)
        await send_friend_request_email(addressee.email, requester.display_name)
    except Exception:
        logger.exception("Failed to send friend request email")


async def send_rating_digests(db: AsyncSession) -> int:
    """Email each user one digest of the unread, not yet emailed friend ratings. Returns mails sent."""
    from sqlalchemy import update

    from core.email import email_enabled, send_rating_digest_email
    from models.media import Media
    from models.users import User

    if not email_enabled():
        logger.info("Rating digest skipped: SMTP_ADDRESS is not configured")
        return 0
    rows = (await db.execute(
        select(Notification)
        .where(Notification.type == FRIEND_RATING, Notification.emailed_at.is_(None))
        .order_by(Notification.user_id, Notification.created_at)
    )).scalars().all()
    if not rows:
        return 0

    users = {u.id: u for u in (await db.execute(
        select(User).options(selectinload(User.profile)).where(User.id.in_({n.user_id for n in rows} | {n.actor_id for n in rows}))
    )).scalars().all()}
    media = {m.id: m for m in (await db.execute(
        select(Media).options(selectinload(Media.show)).where(Media.id.in_({n.media_id for n in rows if n.media_id}))
    )).scalars().all()}

    by_user: dict[int, list[Notification]] = {}
    for n in rows:
        by_user.setdefault(n.user_id, []).append(n)

    sent = 0
    for user_id, notes in by_user.items():
        user = users.get(user_id)
        items = []
        for n in notes:
            m, actor = media.get(n.media_id), users.get(n.actor_id)
            if n.is_read or not m or not actor:
                continue
            title = m.show.title if m.media_type == "episode" and m.show else m.title
            if n.season_number is not None:
                title = f"{title} (season {n.season_number})"
            items.append((actor.display_name, title, n.rating))
        # Mark first so a failing mail server can't cause the same digest to be resent forever.
        await db.execute(update(Notification).where(Notification.id.in_([n.id for n in notes])).values(emailed_at=func.now()))
        await db.commit()
        if not items or not user or not user.email_confirmed:
            continue
        try:
            await send_rating_digest_email(user.email, items)
            sent += 1
        except Exception:
            logger.exception("Failed to send rating digest to user %s", user_id)
    return sent

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.friendship import Friendship

ACCEPTED = "accepted"
PENDING = "pending"


def _pair(a: int, b: int):
    return or_(
        and_(Friendship.requester_id == a, Friendship.addressee_id == b),
        and_(Friendship.requester_id == b, Friendship.addressee_id == a),
    )


async def get_friendship(db: AsyncSession, a: int, b: int) -> Friendship | None:
    result = await db.execute(select(Friendship).where(_pair(a, b)))
    return result.scalars().first()


async def are_friends(db: AsyncSession, a: int, b: int) -> bool:
    result = await db.execute(
        select(Friendship.id).where(_pair(a, b), Friendship.status == ACCEPTED)
    )
    return result.first() is not None


async def friend_ids(db: AsyncSession, user_id: int) -> list[int]:
    result = await db.execute(
        select(Friendship.requester_id, Friendship.addressee_id).where(
            Friendship.status == ACCEPTED,
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
        )
    )
    return [b if a == user_id else a for a, b in result.all()]


def status_for(friendship: Friendship | None, viewer_id: int) -> str:
    """none | friends | request_sent | request_received, from the viewer's side."""
    if friendship is None:
        return "none"
    if friendship.status == ACCEPTED:
        return "friends"
    return "request_sent" if friendship.requester_id == viewer_id else "request_received"


async def friendship_statuses(db: AsyncSession, viewer_id: int, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(Friendship).where(
            or_(
                and_(Friendship.requester_id == viewer_id, Friendship.addressee_id.in_(user_ids)),
                and_(Friendship.addressee_id == viewer_id, Friendship.requester_id.in_(user_ids)),
            )
        )
    )
    statuses = {}
    for f in result.scalars().all():
        other = f.addressee_id if f.requester_id == viewer_id else f.requester_id
        statuses[other] = status_for(f, viewer_id)
    return statuses

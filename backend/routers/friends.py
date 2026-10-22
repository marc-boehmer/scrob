from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.friends import ACCEPTED, PENDING, get_friendship
from core.notifications import clear_friend_request, notify_friend_request
from db import get_db
from dependencies import get_current_user
from models.friendship import Friendship
from models.profile import UserProfileData
from models.users import User

router = APIRouter()


async def _people(db: AsyncSession, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    result = await db.execute(
        select(User, UserProfileData)
        .outerjoin(UserProfileData, UserProfileData.user_id == User.id)
        .where(User.id.in_(ids))
    )
    return {
        u.id: {
            "id": u.id,
            "display_name": p.display_name if p and p.display_name else u.username,
            "avatar_url": f"/profile/avatar/{u.id}" if (p and p.avatar_path) else None,
        }
        for u, p in result.all()
    }


@router.get("")
async def list_friends(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Friendship).where(
            Friendship.status == ACCEPTED,
            or_(Friendship.requester_id == current_user.id, Friendship.addressee_id == current_user.id),
        ).order_by(Friendship.created_at.desc())
    )).scalars().all()
    ids = [f.addressee_id if f.requester_id == current_user.id else f.requester_id for f in rows]
    people = await _people(db, ids)
    return {"friends": [people[i] for i in ids if i in people]}


@router.get("/requests")
async def list_requests(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Friendship).where(
            Friendship.status == PENDING,
            or_(Friendship.requester_id == current_user.id, Friendship.addressee_id == current_user.id),
        ).order_by(Friendship.created_at.desc())
    )).scalars().all()
    incoming = [f.requester_id for f in rows if f.addressee_id == current_user.id]
    outgoing = [f.addressee_id for f in rows if f.requester_id == current_user.id]
    people = await _people(db, incoming + outgoing)
    return {
        "incoming": [people[i] for i in incoming if i in people],
        "outgoing": [people[i] for i in outgoing if i in people],
    }


@router.post("/{user_id}/request")
async def send_request(user_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot send a friend request to yourself.")
    target = (await db.execute(select(User.id).where(User.id == user_id))).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    existing = await get_friendship(db, current_user.id, user_id)
    if existing:
        if existing.status == ACCEPTED:
            return {"status": "friends"}
        if existing.requester_id == current_user.id:
            return {"status": "request_sent"}
        # They already asked us: sending a request back accepts theirs.
        existing.status = ACCEPTED
        await clear_friend_request(db, requester_id=user_id, addressee_id=current_user.id)
        await db.commit()
        return {"status": "friends"}

    db.add(Friendship(requester_id=current_user.id, addressee_id=user_id, status=PENDING))
    notify_friend_request(db, requester_id=current_user.id, addressee_id=user_id)
    await db.commit()
    return {"status": "request_sent"}


@router.post("/{user_id}/accept")
async def accept_request(user_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    friendship = await get_friendship(db, current_user.id, user_id)
    if not friendship or friendship.status != PENDING or friendship.addressee_id != current_user.id:
        raise HTTPException(status_code=404, detail="No pending friend request from this user.")
    friendship.status = ACCEPTED
    await clear_friend_request(db, requester_id=user_id, addressee_id=current_user.id)
    await db.commit()
    return {"status": "friends"}


@router.delete("/{user_id}")
async def remove_friendship(user_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Unfriend, cancel an outgoing request, or decline an incoming one."""
    friendship = await get_friendship(db, current_user.id, user_id)
    if friendship:
        await clear_friend_request(db, friendship.requester_id, friendship.addressee_id)
        await db.delete(friendship)
        await db.commit()
    return {"status": "none"}

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AllowedUser


async def is_user_allowed(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(
        select(AllowedUser).where(AllowedUser.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def grant_access(
    session: AsyncSession,
    user_id: int,
    granted_by: int,
    note: str | None = None,
) -> AllowedUser:
    # upsert: update note if already exists
    result = await session.execute(
        select(AllowedUser).where(AllowedUser.user_id == user_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.note = note
        existing.granted_by = granted_by
        await session.commit()
        return existing

    entry = AllowedUser(user_id=user_id, granted_by=granted_by, note=note)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def revoke_access(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(
        delete(AllowedUser).where(AllowedUser.user_id == user_id)
    )
    await session.commit()
    return result.rowcount > 0


async def list_allowed_users(session: AsyncSession) -> list[AllowedUser]:
    result = await session.execute(
        select(AllowedUser).order_by(AllowedUser.granted_at)
    )
    return list(result.scalars().all())

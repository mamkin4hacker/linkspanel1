import uuid
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Link


async def create_link(session: AsyncSession, autocommit: bool = True, **kwargs) -> Link:
    obj = Link(**kwargs)
    session.add(obj)
    if autocommit:
        await session.commit()
        await session.refresh(obj)
    else:
        await session.flush()
    return obj


async def get_link_by_subdomain_and_id(
    session: AsyncSession, subdomain: str, link_id: str
) -> Link | None:
    result = await session.execute(
        select(Link).where(
            Link.subdomain == subdomain,
            Link.link_id == link_id,
            Link.is_active == True,
        )
    )
    return result.scalar_one_or_none()


async def get_links_by_user(
    session: AsyncSession, user_id: int, offset: int = 0, limit: int = 10
) -> Sequence[Link]:
    result = await session.execute(
        select(Link)
        .where(Link.user_id == user_id, Link.is_active == True)
        .order_by(Link.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def count_links_by_user(session: AsyncSession, user_id: int) -> int:
    from sqlalchemy import func
    result = await session.execute(
        select(func.count()).select_from(Link).where(
            Link.user_id == user_id, Link.is_active == True
        )
    )
    return result.scalar_one()


async def get_link_by_id(session: AsyncSession, link_id: uuid.UUID) -> Link | None:
    result = await session.execute(
        select(Link).where(Link.id == link_id)
    )
    return result.scalar_one_or_none()


async def soft_delete_link(session: AsyncSession, link_id: uuid.UUID, autocommit: bool = True) -> None:
    await session.execute(
        update(Link).where(Link.id == link_id).values(is_active=False)
    )
    if autocommit:
        await session.commit()


async def increment_visits(session: AsyncSession, link_id: uuid.UUID, autocommit: bool = True) -> None:
    await session.execute(
        update(Link).where(Link.id == link_id).values(visits=Link.visits + 1)
    )
    if autocommit:
        await session.commit()

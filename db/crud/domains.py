import uuid
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Domain


async def get_least_loaded_domain(session: AsyncSession) -> Domain | None:
    result = await session.execute(
        select(Domain)
        .where(Domain.is_active == True)
        .order_by(Domain.subdomain_count.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


async def increment_subdomain_count(session: AsyncSession, domain_id: uuid.UUID) -> None:
    await session.execute(
        update(Domain)
        .where(Domain.id == domain_id)
        .values(subdomain_count=Domain.subdomain_count + 1)
    )


async def decrement_subdomain_count(session: AsyncSession, domain_id: uuid.UUID) -> None:
    await session.execute(
        update(Domain)
        .where(Domain.id == domain_id, Domain.subdomain_count > 0)
        .values(subdomain_count=Domain.subdomain_count - 1)
    )


async def get_all_active_domains(session: AsyncSession) -> Sequence[Domain]:
    result = await session.execute(
        select(Domain).where(Domain.is_active == True).order_by(Domain.subdomain_count.asc())
    )
    return result.scalars().all()


async def create_domain(session: AsyncSession, domain: str, autocommit: bool = True) -> Domain:
    obj = Domain(domain=domain)
    session.add(obj)
    if autocommit:
        await session.commit()
        await session.refresh(obj)
    else:
        await session.flush()
    return obj

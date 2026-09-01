import uuid
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Domain


async def get_user_domain(session: AsyncSession, user_id: int) -> Domain | None:
    """Return the domain assigned to this user, or None if they have none."""
    result = await session.execute(
        select(Domain).where(Domain.user_id == user_id, Domain.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_unassigned_domains(session: AsyncSession) -> Sequence[Domain]:
    """Return all active domains that have no user assigned."""
    result = await session.execute(
        select(Domain)
        .where(Domain.is_active == True, Domain.user_id == None)
        .order_by(Domain.domain)
    )
    return result.scalars().all()


async def assign_domain_to_user(
    session: AsyncSession,
    domain_id: uuid.UUID,
    user_id: int,
    autocommit: bool = True,
) -> Domain | None:
    """
    Assign an unassigned domain to a user.
    Returns the domain on success, None if the domain is already assigned
    or the user already owns a domain.
    """
    result = await session.execute(
        select(Domain)
        .where(Domain.id == domain_id)
        .with_for_update(skip_locked=False)
    )
    domain = result.scalar_one_or_none()
    if domain is None or domain.user_id is not None:
        return None  # domain already taken

    # ensure user doesn't already own a domain
    existing = await session.execute(
        select(Domain).where(Domain.user_id == user_id)
    )
    if existing.scalar_one_or_none() is not None:
        return None  # user already has a domain

    domain.user_id = user_id
    if autocommit:
        await session.commit()
        await session.refresh(domain)
    else:
        await session.flush()
    return domain


async def unassign_domain_from_user(
    session: AsyncSession,
    user_id: int,
    autocommit: bool = True,
) -> bool:
    """Remove domain ownership from a user, returning it to the pool."""
    result = await session.execute(
        update(Domain)
        .where(Domain.user_id == user_id)
        .values(user_id=None)
        .returning(Domain.id)
    )
    if autocommit:
        await session.commit()
    return result.rowcount > 0


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

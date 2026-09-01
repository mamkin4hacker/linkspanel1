from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Visitor


async def get_or_create_visitor(
    session: AsyncSession,
    ip: str,
    city: str | None = None,
    country: str | None = None,
    device: str | None = None,
    sys_lang: str | None = None,
    autocommit: bool = True,
) -> tuple[Visitor, bool]:
    """Returns (visitor, is_new)."""
    result = await session.execute(select(Visitor).where(Visitor.ip == ip))
    visitor = result.scalar_one_or_none()
    is_new = visitor is None
    if is_new:
        visitor = Visitor(
            ip=ip,
            city=city,
            country=country,
            device=device,
            sys_lang=sys_lang,
        )
        session.add(visitor)
        if autocommit:
            await session.commit()
            await session.refresh(visitor)
        else:
            await session.flush()
    return visitor, is_new

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Template


async def create_template(session: AsyncSession, user_id: int, autocommit: bool = True, **kwargs) -> Template:
    obj = Template(user_id=user_id, **kwargs)
    session.add(obj)
    if autocommit:
        await session.commit()
        await session.refresh(obj)
    else:
        await session.flush()
    return obj


async def get_template_by_id(session: AsyncSession, template_id: uuid.UUID) -> Template | None:
    result = await session.execute(
        select(Template).where(Template.id == template_id)
    )
    return result.scalar_one_or_none()


async def update_template(
    session: AsyncSession, template_id: uuid.UUID, autocommit: bool = True, **kwargs
) -> Template | None:
    obj = await get_template_by_id(session, template_id)
    if obj is None:
        return None
    for key, value in kwargs.items():
        setattr(obj, key, value)
    if autocommit:
        await session.commit()
        await session.refresh(obj)
    else:
        await session.flush()
    return obj

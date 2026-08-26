from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


async def get_or_create_user(
    session: AsyncSession, user_id: int, username: str | None = None, autocommit: bool = True
) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=user_id, username=username)
        session.add(user)
        if autocommit:
            await session.commit()
            await session.refresh(user)
        else:
            await session.flush()
    elif username and user.username != username:
        user.username = username
        if autocommit:
            await session.commit()
    return user

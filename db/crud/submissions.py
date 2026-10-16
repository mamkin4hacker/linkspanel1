from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Submission

_KEEP_EMPTY = {"session_id", "visitor_id", "subdomain", "link_id"}


async def upsert_submission(session: AsyncSession, autocommit: bool = True, **fields) -> Submission:
    session_id = (fields.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id required")

    result = await session.execute(select(Submission).where(Submission.session_id == session_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = Submission(session_id=session_id)
        session.add(row)

    for key, value in fields.items():
        if key == "session_id" or not hasattr(row, key):
            continue
        if key not in _KEEP_EMPTY and value in (None, ""):
            continue
        setattr(row, key, value)

    if autocommit:
        await session.commit()
        await session.refresh(row)
    else:
        await session.flush()
    return row

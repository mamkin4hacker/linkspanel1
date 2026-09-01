"""
AccessMiddleware — blocks all users except super-admins and those in allowed_users.

Super-admin IDs come from the SUPER_ADMIN_IDS env var (comma-separated).
Everyone else must be explicitly granted access via the admin panel.
"""
import logging
import os
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from db.crud.allowed_users import is_user_allowed
from db.session import get_session

logger = logging.getLogger(__name__)

_ACCESS_DENIED_TEXT = (
    "⛔️ У вас нет доступа к этому боту.\n"
    "Обратитесь к администратору."
)


def _get_super_admin_ids() -> set[int]:
    raw = os.getenv("SUPER_ADMIN_IDS", os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")))
    result = set(
        int(x.strip())
        for x in raw.split(",")
        if x.strip().lstrip("-").isdigit()
    )
    logger.info("SUPER_ADMIN_IDS loaded: %s", result)
    return result


_SUPER_ADMIN_IDS: set[int] = _get_super_admin_ids()


def is_super_admin(user_id: int) -> bool:
    return user_id in _SUPER_ADMIN_IDS


class AccessMiddleware(BaseMiddleware):
    """Outer update middleware — runs before any handler."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # event_from_user is populated by aiogram for all user-originated updates
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        user_id: int = user.id
        logger.debug("AccessMiddleware: user_id=%s, super_admin_ids=%s", user_id, _SUPER_ADMIN_IDS)

        if is_super_admin(user_id):
            data["is_super_admin"] = True
            return await handler(event, data)

        # check DB for granted access
        try:
            async with get_session() as session:
                allowed = await is_user_allowed(session, user_id)
        except Exception as e:
            logger.error("AccessMiddleware DB error: %s", e)
            # on DB error let the update through rather than silently dropping it
            data["is_super_admin"] = False
            return await handler(event, data)

        if not allowed:
            logger.info("AccessMiddleware: blocked user_id=%s", user_id)
            # extract the real message/callback from the Update to reply
            update = event if isinstance(event, Update) else None
            if update is not None:
                if update.message:
                    await update.message.answer(_ACCESS_DENIED_TEXT)
                elif update.callback_query:
                    await update.callback_query.answer(_ACCESS_DENIED_TEXT, show_alert=True)
            return

        data["is_super_admin"] = False
        return await handler(event, data)

"""
AccessMiddleware — blocks all users except super-admins and those in allowed_users.

Super-admin IDs come from the SUPER_ADMIN_IDS env var (comma-separated).
Everyone else must be explicitly granted access via the admin panel.
"""
import os
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from db.crud.allowed_users import is_user_allowed
from db.session import get_session

_SUPER_ADMIN_IDS: set[int] = set(
    int(x.strip())
    for x in os.getenv("SUPER_ADMIN_IDS", os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0"))).split(",")
    if x.strip().lstrip("-").isdigit()
)

_ACCESS_DENIED_TEXT = (
    "⛔️ У вас нет доступа к этому боту.\n"
    "Обратитесь к администратору."
)


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
        user = data.get("event_from_user")
        if user is None:
            # non-user updates (channel posts, etc.) — pass through
            return await handler(event, data)

        user_id: int = user.id

        # super-admins always have access
        if is_super_admin(user_id):
            data["is_super_admin"] = True
            return await handler(event, data)

        # check DB for granted access
        async with get_session() as session:
            allowed = await is_user_allowed(session, user_id)

        if not allowed:
            # reply politely and stop propagation
            if isinstance(event, Message):
                await event.answer(_ACCESS_DENIED_TEXT)
            elif isinstance(event, CallbackQuery):
                await event.answer(_ACCESS_DENIED_TEXT, show_alert=True)
            return  # do NOT call handler

        data["is_super_admin"] = False
        return await handler(event, data)

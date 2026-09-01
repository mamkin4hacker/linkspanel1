"""
Admin panel handler.

Only super-admins can access this. Accessible via "👑 Админ панель" button
in the main menu (shown only to super-admins) or via /admin command.

Features:
- List all users who have access
- Grant access by Telegram user ID (with optional note)
- Revoke access from a user
"""
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    admin_panel_kb,
    admin_users_list_kb,
    admin_cancel_kb,
    main_menu_kb,
)
from db.crud.allowed_users import (
    grant_access,
    list_allowed_users,
    revoke_access,
)
from db.session import get_session

router = Router()

_SUPER_ADMIN_IDS: set[int] = set(
    int(x.strip())
    for x in os.getenv(
        "SUPER_ADMIN_IDS", os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0"))
    ).split(",")
    if x.strip().lstrip("-").isdigit()
)


def is_super_admin(user_id: int) -> bool:
    return user_id in _SUPER_ADMIN_IDS


# ── FSM ────────────────────────────────────────────────────────────────────────

class AdminPanel(StatesGroup):
    waiting_grant_id   = State()   # waiting for user_id to grant
    waiting_grant_note = State()   # waiting for optional note
    waiting_revoke_id  = State()   # waiting for user_id to revoke


# ── helpers ────────────────────────────────────────────────────────────────────

async def _render_user_list() -> str:
    async with get_session() as session:
        users = await list_allowed_users(session)

    if not users:
        return "📋 <b>Список разрешённых пользователей пуст.</b>"

    lines = ["📋 <b>Разрешённые пользователи:</b>\n"]
    for u in users:
        note_part = f" — {u.note}" if u.note else ""
        lines.append(f"• <code>{u.user_id}</code>{note_part}")
    return "\n".join(lines)


# ── /admin command & button ────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "👑 <b>Админ панель</b>\nВыберите действие:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )


@router.message(F.text == "👑 Админ панель")
async def btn_admin_panel(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "👑 <b>Админ панель</b>\nВыберите действие:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )


# ── list users ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:list")
async def admin_list(call: CallbackQuery):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    text = await _render_user_list()
    async with get_session() as session:
        users = await list_allowed_users(session)
    await call.message.edit_text(
        text,
        reply_markup=admin_users_list_kb(users),
        parse_mode="HTML",
    )
    await call.answer()


# ── grant access: ask for user_id ─────────────────────────────────────────────

@router.callback_query(F.data == "admin:grant")
async def admin_grant_start(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminPanel.waiting_grant_id)
    await call.message.answer(
        "Введите <b>Telegram ID</b> пользователя, которому хотите дать доступ.\n"
        "Узнать ID можно через @userinfobot или @getmyid_bot.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminPanel.waiting_grant_id)
async def admin_grant_receive_id(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw.lower() == "отмена":
        await state.clear()
        await message.answer(
            "👑 <b>Админ панель</b>\nВыберите действие:",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        return
    if not raw.lstrip("-").isdigit():
        await message.answer("Некорректный ID. Введите числовой Telegram ID:")
        return
    await state.update_data(grant_target_id=int(raw))
    await state.set_state(AdminPanel.waiting_grant_note)
    await message.answer(
        "Введите заметку для этого пользователя (необязательно).\n"
        "Или напишите <code>-</code> чтобы пропустить.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminPanel.waiting_grant_note)
async def admin_grant_receive_note(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw.lower() == "отмена":
        await state.clear()
        await message.answer(
            "👑 <b>Админ панель</b>\nВыберите действие:",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        return
    note = None if raw == "-" else raw[:200]
    data = await state.get_data()
    target_id: int = data["grant_target_id"]

    async with get_session() as session:
        await grant_access(session, user_id=target_id, granted_by=message.from_user.id, note=note)

    await state.clear()
    note_display = f" ({note})" if note else ""
    await message.answer(
        f"✅ Пользователю <code>{target_id}</code>{note_display} выдан доступ.",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )

    # notify the user if possible
    try:
        await message.bot.send_message(
            target_id,
            "✅ Вам выдан доступ к боту. Нажмите /start чтобы начать.",
        )
    except Exception:
        pass  # user may not have started the bot yet


# ── revoke access: ask for user_id ────────────────────────────────────────────

@router.callback_query(F.data == "admin:revoke")
async def admin_revoke_start(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminPanel.waiting_revoke_id)
    await call.message.answer(
        "Введите <b>Telegram ID</b> пользователя, у которого хотите отозвать доступ:",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:revoke:"))
async def admin_revoke_inline(call: CallbackQuery):
    """Revoke directly from the user list (inline button)."""
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    target_id = int(call.data.split(":")[2])
    async with get_session() as session:
        removed = await revoke_access(session, target_id)

    if removed:
        await call.answer(f"✅ Доступ пользователя {target_id} отозван.", show_alert=True)
    else:
        await call.answer(f"Пользователь {target_id} не найден.", show_alert=True)

    # refresh the list view
    text = await _render_user_list()
    async with get_session() as session:
        users = await list_allowed_users(session)
    try:
        await call.message.edit_text(
            text,
            reply_markup=admin_users_list_kb(users),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(AdminPanel.waiting_revoke_id)
async def admin_revoke_receive_id(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw.lower() == "отмена":
        await state.clear()
        await message.answer(
            "👑 <b>Админ панель</b>\nВыберите действие:",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        return
    if not raw.lstrip("-").isdigit():
        await message.answer("Некорректный ID. Введите числовой Telegram ID:")
        return
    target_id = int(raw)
    async with get_session() as session:
        removed = await revoke_access(session, target_id)

    await state.clear()
    if removed:
        await message.answer(
            f"✅ Доступ пользователя <code>{target_id}</code> отозван.",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        try:
            await message.bot.send_message(
                target_id,
                "⛔️ Ваш доступ к боту был отозван администратором.",
            )
        except Exception:
            pass
    else:
        await message.answer(
            f"Пользователь <code>{target_id}</code> не найден в списке разрешённых.",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )


# ── back to main menu ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:back")
async def admin_back(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await call.message.answer(
        "Главное меню",
        reply_markup=main_menu_kb(is_super_admin=True),
    )
    await call.answer()


@router.callback_query(F.data == "admin:back_to_panel")
async def admin_back_to_panel(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(
        "👑 <b>Админ панель</b>\nВыберите действие:",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )
    await call.answer()

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
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    admin_panel_kb,
    admin_users_list_kb,
    admin_cancel_kb,
    admin_domain_list_kb,
    main_menu_kb,
)
from bot.utils.cloudflare import check_dns
from bot.utils.certbot import issue_cert
from bot.utils.nginx_conf import write_domain_conf, reload_nginx
from db.crud.allowed_users import (
    grant_access,
    list_allowed_users,
    revoke_access,
)
from db.crud.domains import (
    assign_domain_to_user,
    create_domain,
    get_unassigned_domains,
    get_user_domain,
    unassign_domain_from_user,
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
    # domain assignment
    assign_domain_pick_user   = State()
    assign_domain_pick_domain = State()
    # domain provisioning
    add_domain_input = State()     # waiting for domain name to provision


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


# ── assign domain: entry ──────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:assign_domain")
async def admin_assign_domain_start(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminPanel.assign_domain_pick_user)
    await call.message.answer(
        "Введите <b>Telegram ID</b> пользователя, которому хотите назначить домен:",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminPanel.assign_domain_pick_user)
async def admin_assign_domain_receive_user(message: Message, state: FSMContext):
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
        current = await get_user_domain(session, target_id)
        domains = await get_unassigned_domains(session)

    if current:
        await message.answer(
            f"У пользователя <code>{target_id}</code> уже есть домен: "
            f"<code>{current.domain}</code>.\n"
            "Сначала снимите текущее назначение, если хотите переназначить.\n\n"
            f"Для снятия: <code>/unassign {target_id}</code>",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        await state.clear()
        return

    if not domains:
        await message.answer(
            "Нет свободных доменов для назначения.",
            reply_markup=admin_panel_kb(),
        )
        await state.clear()
        return

    await state.update_data(assign_target_user_id=target_id)
    await state.set_state(AdminPanel.assign_domain_pick_domain)
    await message.answer(
        f"Выберите домен для пользователя <code>{target_id}</code>:",
        reply_markup=admin_domain_list_kb(domains),
        parse_mode="HTML",
    )


@router.callback_query(AdminPanel.assign_domain_pick_domain, F.data.startswith("admin:domain_pick:"))
async def admin_assign_domain_confirm(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    import uuid as _uuid
    domain_id = _uuid.UUID(call.data.split(":")[2])
    data = await state.get_data()
    target_user_id: int = data["assign_target_user_id"]

    async with get_session() as session:
        domain = await assign_domain_to_user(session, domain_id, target_user_id)

    await state.clear()
    if domain is None:
        await call.message.answer(
            "Не удалось назначить домен — он уже занят или у пользователя уже есть домен.",
            reply_markup=admin_panel_kb(),
        )
    else:
        await call.message.answer(
            f"✅ Домен <code>{domain.domain}</code> назначен пользователю <code>{target_user_id}</code>.",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        try:
            await call.bot.send_message(
                target_user_id,
                f"✅ Вам назначен домен <code>{domain.domain}</code>. "
                "Теперь вы можете создавать ссылки.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    await call.answer()


# ── unassign domain (inline, no FSM) ──────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:unassign_domain:"))
async def admin_unassign_domain_inline(call: CallbackQuery):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    target_id = int(call.data.split(":")[2])
    async with get_session() as session:
        removed = await unassign_domain_from_user(session, target_id)
    if removed:
        await call.answer(f"Домен пользователя {target_id} освобождён.", show_alert=True)
    else:
        await call.answer(f"У пользователя {target_id} нет назначенного домена.", show_alert=True)


# ── add domain: full auto-provisioning ───────────────────────────────────────

_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


@router.callback_query(F.data == "admin:add_domain")
async def admin_add_domain_start(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminPanel.add_domain_input)
    await call.message.answer(
        "Введите доменное имя для добавления в пул.\n"
        "Например: <code>mysite.com</code>\n\n"
        "<b>Перед добавлением убедись, что в Cloudflare настроены:</b>\n"
        "• A-запись <code>@</code> → IP сервера\n"
        "• A-запись <code>*</code> → IP сервера",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminPanel.add_domain_input)
async def admin_add_domain_receive(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return

    raw = (message.text or "").strip().lower()

    if raw == "отмена":
        await state.clear()
        await message.answer(
            "👑 <b>Админ панель</b>\nВыберите действие:",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        return

    # Basic format validation
    if not _DOMAIN_RE.match(raw):
        await message.answer(
            "Некорректное доменное имя. Введи в формате <code>example.com</code>:",
            parse_mode="HTML",
        )
        return

    # Check domain not already in DB
    async with get_session() as session:
        from sqlalchemy import select
        from db.models import Domain
        exists = await session.execute(
            select(Domain).where(Domain.domain == raw)
        )
        if exists.scalar_one_or_none():
            await message.answer(
                f"Домен <code>{raw}</code> уже есть в базе.",
                reply_markup=admin_panel_kb(),
                parse_mode="HTML",
            )
            await state.clear()
            return

    await state.clear()

    # ── Step 1: DNS check ────────────────────────────────────────────────────
    status_msg = await message.answer(
        f"⏳ Проверяю DNS для <code>{raw}</code>...",
        parse_mode="HTML",
    )

    dns_ok, dns_err = await check_dns(raw)
    if not dns_ok:
        await status_msg.edit_text(
            f"❌ <b>Ошибка DNS</b>\n\n{dns_err}",
            parse_mode="HTML",
            reply_markup=admin_panel_kb(),
        )
        return

    # ── Step 2: SSL certificate ──────────────────────────────────────────────
    await status_msg.edit_text(
        f"✅ DNS в порядке\n\n⏳ Выпускаю SSL-сертификат для <code>{raw}</code>...\n"
        "<i>Это займёт 30–60 секунд</i>",
        parse_mode="HTML",
    )

    cert_ok, cert_err = await issue_cert(raw)
    if not cert_ok:
        await status_msg.edit_text(
            f"✅ DNS в порядке\n❌ <b>Ошибка certbot</b>\n\n{cert_err}",
            parse_mode="HTML",
            reply_markup=admin_panel_kb(),
        )
        return

    # ── Step 3: nginx config ─────────────────────────────────────────────────
    await status_msg.edit_text(
        f"✅ DNS в порядке\n✅ SSL-сертификат выпущен\n\n"
        f"⏳ Настраиваю nginx для <code>{raw}</code>...",
        parse_mode="HTML",
    )

    try:
        write_domain_conf(raw)
    except Exception as e:
        await status_msg.edit_text(
            f"✅ DNS в порядке\n✅ SSL-сертификат выпущен\n"
            f"❌ <b>Не удалось записать nginx конфиг:</b> <code>{e}</code>",
            parse_mode="HTML",
            reply_markup=admin_panel_kb(),
        )
        return

    reload_ok, reload_err = await reload_nginx()
    if not reload_ok:
        # nginx config written but reload failed — still add to DB, warn admin
        async with get_session() as session:
            await create_domain(session, raw)
        await status_msg.edit_text(
            f"✅ DNS в порядке\n✅ SSL-сертификат выпущен\n"
            f"⚠️ <b>nginx reload не прошёл:</b>\n{reload_err}\n\n"
            f"Домен <code>{raw}</code> добавлен в базу, но nginx нужно перезапустить вручную:\n"
            f"<code>docker compose restart nginx</code>",
            parse_mode="HTML",
            reply_markup=admin_panel_kb(),
        )
        return

    # ── Step 4: add to DB ────────────────────────────────────────────────────
    async with get_session() as session:
        await create_domain(session, raw)

    await status_msg.edit_text(
        f"✅ DNS в порядке\n✅ SSL-сертификат выпущен\n✅ nginx настроен\n\n"
        f"🎉 Домен <code>{raw}</code> добавлен в пул и готов к использованию.\n"
        f"Назначь его пользователю через <b>Назначить домен</b>.",
        parse_mode="HTML",
        reply_markup=admin_panel_kb(),
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

import math
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from api.cache import invalidate
from bot.keyboards import (
    confirm_delete_kb,
    editor_menu_edit_kb,
    link_detail_kb,
    links_list_kb,
    main_menu_kb,
)
from bot.states import CreateLink, ManageLinks
from db.crud.domains import decrement_subdomain_count
from db.crud.links import (
    count_links_by_user,
    get_link_by_id,
    get_links_by_user,
    soft_delete_link,
)
from db.crud.templates import update_template
from db.session import get_session

router = Router()
PAGE_SIZE = 10


# ──────────────────────────────────────────────
# Entry: "Мои ссылки"
# ──────────────────────────────────────────────

async def _show_links_page(target, user_id: int, page: int, state: FSMContext):
    async with get_session() as session:
        total = await count_links_by_user(session, user_id)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        links = await get_links_by_user(session, user_id, offset=page * PAGE_SIZE, limit=PAGE_SIZE)

    await state.set_state(ManageLinks.list_view)
    await state.update_data(links_page=page)

    if not links:
        if isinstance(target, Message):
            await target.answer("У тебя пока нет ссылок. Создай первую!", reply_markup=main_menu_kb())
        else:
            await target.message.answer("У тебя пока нет ссылок. Создай первую!", reply_markup=main_menu_kb())
        return

    text = f"<b>Мои ссылки</b> (страница {page + 1}/{total_pages}):"
    kb = links_list_kb(links, page, total_pages)

    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()


@router.message(F.text == "Мои ссылки")
async def cmd_my_links(message: Message, state: FSMContext):
    await state.clear()
    await _show_links_page(message, message.from_user.id, 0, state)


@router.callback_query(F.data == "goto:mylinks")
async def goto_mylinks(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _show_links_page(call, call.from_user.id, 0, state)


@router.callback_query(ManageLinks.list_view, F.data.startswith("page:"))
async def paginate_links(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[1])
    await _show_links_page(call, call.from_user.id, page, state)


# ──────────────────────────────────────────────
# Link detail
# ──────────────────────────────────────────────

@router.callback_query(ManageLinks.list_view, F.data.startswith("link:"))
async def show_link_detail(call: CallbackQuery, state: FSMContext):
    link_uuid = call.data.split(":", 1)[1]
    await state.set_state(ManageLinks.link_detail)
    await state.update_data(current_link_id=link_uuid)

    async with get_session() as session:
        link = await get_link_by_id(session, uuid.UUID(link_uuid))

    if not link:
        await call.answer("Ссылка не найдена.", show_alert=True)
        return

    text = (
        f"<b>{link.full_url}</b>\n\n"
        f"Переходов: {link.visits}\n"
        f"Поддомен: {link.subdomain}\n"
        f"Домен: {link.domain.domain}"
    )
    await call.message.answer(text, reply_markup=link_detail_kb(link_uuid), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "back:list")
async def back_to_list(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get("links_page", 0)
    await _show_links_page(call, call.from_user.id, page, state)


# ──────────────────────────────────────────────
# Copy URL
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("copy:"))
async def copy_url(call: CallbackQuery, state: FSMContext):
    link_uuid = call.data.split(":", 1)[1]
    async with get_session() as session:
        link = await get_link_by_id(session, uuid.UUID(link_uuid))
    if link:
        await call.message.answer(f"<code>{link.full_url}</code>", parse_mode="HTML")
    await call.answer("URL скопирован в сообщение")


# ──────────────────────────────────────────────
# Edit existing link
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("editlink:"))
async def edit_existing_link(call: CallbackQuery, state: FSMContext):
    link_uuid = call.data.split(":", 1)[1]

    async with get_session() as session:
        link = await get_link_by_id(session, uuid.UUID(link_uuid))

    if not link:
        await call.answer("Ссылка не найдена.", show_alert=True)
        return

    tpl = link.template
    template_data = {
        "bg_color": tpl.bg_color,
        "text_color": tpl.text_color,
        "font_family": tpl.font_family,
        "title": tpl.title,
        "description": tpl.description,
        "button_text": tpl.button_text,
        "button_url": tpl.button_url,
        "favicon_url": tpl.favicon_url,
        "custom_css": tpl.custom_css,
    }

    await state.set_state(CreateLink.editing_template)
    await state.update_data(
        subdomain=link.subdomain,
        template=template_data,
        editing_link_id=link_uuid,
        editing_template_id=str(tpl.id),
        cache_key=f"page:{link.subdomain}:{link.link_id}",
    )

    from bot.handlers.editor import _editor_text
    data = await state.get_data()
    await call.message.answer(
        _editor_text(data),
        reply_markup=editor_menu_edit_kb(template_data),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:save")
async def save_edited_link(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    template_id = data.get("editing_template_id")
    cache_key = data.get("cache_key")
    tpl_data = data.get("template", {})

    if not template_id:
        await call.answer("Ошибка: нет шаблона для сохранения.", show_alert=True)
        return

    async with get_session() as session:
        await update_template(session, uuid.UUID(template_id), **tpl_data)

    if cache_key:
        await invalidate(cache_key)

    await state.clear()
    await call.message.answer("💾 Изменения сохранены!")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:back_to_list")
async def editor_back_to_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _show_links_page(call, call.from_user.id, 0, state)


# ──────────────────────────────────────────────
# Delete link
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("delete:"))
async def ask_delete_confirm(call: CallbackQuery, state: FSMContext):
    link_uuid = call.data.split(":", 1)[1]

    async with get_session() as session:
        link = await get_link_by_id(session, uuid.UUID(link_uuid))

    if not link:
        await call.answer("Ссылка не найдена.", show_alert=True)
        return

    await state.set_state(ManageLinks.confirm_delete)
    await call.message.answer(
        f"Удалить ссылку <code>{link.full_url}</code>?",
        reply_markup=confirm_delete_kb(link_uuid),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(ManageLinks.confirm_delete, F.data.startswith("confirmdelete:"))
async def do_delete_link(call: CallbackQuery, state: FSMContext):
    link_uuid = call.data.split(":", 1)[1]

    async with get_session() as session:
        link = await get_link_by_id(session, uuid.UUID(link_uuid))
        if not link:
            await call.answer("Ссылка не найдена.", show_alert=True)
            return
        cache_key = f"page:{link.subdomain}:{link.link_id}"
        domain_id = link.domain_id
        await soft_delete_link(session, uuid.UUID(link_uuid), autocommit=False)
        await decrement_subdomain_count(session, domain_id)
        await session.commit()

    await invalidate(cache_key)
    await state.clear()
    await call.message.answer("✅ Ссылка удалена.")
    await call.answer()


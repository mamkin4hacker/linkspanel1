import os
import secrets
import uuid

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import text

from bot.keyboards import after_create_kb, editor_menu_edit_kb, editor_menu_kb
from bot.states import CreateLink
from bot.utils.preview import create_preview
from bot.utils.validators import (
    validate_favicon,
    validate_hex,
    validate_subdomain,
    validate_url,
)
from db.crud.domains import get_least_loaded_domain, increment_subdomain_count
from db.crud.links import create_link
from db.crud.templates import create_template
from db.crud.users import get_or_create_user
from db.session import get_session

router = Router()

PREVIEW_DOMAIN = os.getenv("PREVIEW_DOMAIN", "preview.example.com")


def _default_template() -> dict:
    return {
        "bg_color": "#ffffff",
        "text_color": "#000000",
        "font_family": "Inter, sans-serif",
        "title": "",
        "description": "",
        "button_text": "",
        "button_url": "",
        "favicon_url": "",
        "custom_css": "",
    }


def _editor_text(data: dict) -> str:
    tpl = data.get("template", _default_template())
    subdomain = data.get("subdomain", "—")
    lines = [
        f"<b>Поддомен:</b> <code>{subdomain}</code>",
        "",
        f"Цвет фона: {tpl.get('bg_color', '#ffffff')}",
        f"Цвет текста: {tpl.get('text_color', '#000000')}",
        f"Заголовок: {tpl.get('title') or '(пусто)'}",
        f"Описание: {tpl.get('description') or '(пусто)'}",
        f"Кнопка: {tpl.get('button_text') or '(пусто)'} / {tpl.get('button_url') or '(пусто)'}",
        f"Favicon: {'загружен' if tpl.get('favicon_url') else 'не загружен'}",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Entry: user pressed "Создать ссылку"
# ──────────────────────────────────────────────

@router.message(F.text == "Создать ссылку")
async def start_create(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CreateLink.waiting_subdomain)
    await message.answer(
        "Введи название поддомена.\n"
        "Только латиница, цифры и дефис. Например: <code>my-page</code>",
        parse_mode="HTML",
    )


# ──────────────────────────────────────────────
# Step 1: subdomain input
# ──────────────────────────────────────────────

@router.message(CreateLink.waiting_subdomain)
async def receive_subdomain(message: Message, state: FSMContext):
    value = (message.text or "").strip().lower()
    err = validate_subdomain(value)
    if err:
        await message.answer(f"Ошибка: {err}")
        return

    async with get_session() as session:
        exists = await session.execute(
            text("SELECT 1 FROM links WHERE subdomain = :s AND is_active = true LIMIT 1"),
            {"s": value},
        )
        if exists.scalar():
            await message.answer("Этот поддомен уже занят. Попробуй другое название.")
            return

    await state.update_data(subdomain=value, template=_default_template())
    await state.set_state(CreateLink.editing_template)
    data = await state.get_data()
    await message.answer(
        _editor_text(data),
        reply_markup=editor_menu_kb(data.get("template", {})),
        parse_mode="HTML",
    )


# ──────────────────────────────────────────────
# Step 2: template editor callbacks
# ──────────────────────────────────────────────

@router.callback_query(CreateLink.editing_template, F.data == "edit:bg_color")
async def ask_bg_color(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_bg_color)
    await call.message.answer("Введи цвет фона в формате HEX. Например: <code>#1a2b3c</code>", parse_mode="HTML")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:text_color")
async def ask_text_color(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_text_color)
    await call.message.answer("Введи цвет текста в формате HEX. Например: <code>#ffffff</code>", parse_mode="HTML")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:title")
async def ask_title(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_title)
    await call.message.answer("Введи заголовок страницы (до 200 символов):")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:description")
async def ask_description(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_description)
    await call.message.answer("Введи описание страницы:")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:button")
async def ask_button_text(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_button_text)
    await call.message.answer("Введи текст кнопки (до 100 символов):")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:favicon")
async def ask_favicon(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_favicon)
    await call.message.answer("Отправь файл .ico или .png (до 1 МБ):")
    await call.answer()


@router.callback_query(CreateLink.editing_template, F.data == "edit:custom_css")
async def ask_custom_css(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateLink.editing_custom_css)
    await call.message.answer(
        "Введи CSS (до 5000 символов).\n"
        "<b>Запрещено:</b> url(), @import, expression()",
        parse_mode="HTML",
    )
    await call.answer()


# ──────────────────────────────────────────────
# Field value handlers
# ──────────────────────────────────────────────

async def _back_to_editor(message: Message, state: FSMContext):
    await state.set_state(CreateLink.editing_template)
    data = await state.get_data()
    tpl = data.get("template", {})
    is_editing = bool(data.get("editing_link_id"))
    kb = editor_menu_edit_kb(tpl) if is_editing else editor_menu_kb(tpl)
    await message.answer(
        _editor_text(data),
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(CreateLink.editing_bg_color)
async def receive_bg_color(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    err = validate_hex(value)
    if err:
        await message.answer(f"Ошибка: {err}")
        return
    data = await state.get_data()
    data["template"]["bg_color"] = value
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


@router.message(CreateLink.editing_text_color)
async def receive_text_color(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    err = validate_hex(value)
    if err:
        await message.answer(f"Ошибка: {err}")
        return
    data = await state.get_data()
    data["template"]["text_color"] = value
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


@router.message(CreateLink.editing_title)
async def receive_title(message: Message, state: FSMContext):
    value = (message.text or "")[:200]
    data = await state.get_data()
    data["template"]["title"] = value
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


@router.message(CreateLink.editing_description)
async def receive_description(message: Message, state: FSMContext):
    value = message.text or ""
    data = await state.get_data()
    data["template"]["description"] = value
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


@router.message(CreateLink.editing_button_text)
async def receive_button_text(message: Message, state: FSMContext):
    value = (message.text or "")[:100]
    data = await state.get_data()
    data["template"]["button_text"] = value
    await state.update_data(template=data["template"])
    await state.set_state(CreateLink.editing_button_url)
    await message.answer("Теперь введи URL кнопки:")


@router.message(CreateLink.editing_button_url)
async def receive_button_url(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    err = validate_url(value)
    if err:
        await message.answer(f"Ошибка: {err}")
        return
    data = await state.get_data()
    data["template"]["button_url"] = value
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


@router.message(CreateLink.editing_favicon)
async def receive_favicon(message: Message, state: FSMContext, bot: Bot):
    doc = message.document
    photo = message.photo
    if not doc and not photo:
        await message.answer("Пожалуйста, отправь файл (.ico или .png).")
        return

    if doc:
        mime = doc.mime_type or ""
        size = doc.file_size or 0
        file_id = doc.file_id
        ext = ".ico" if "icon" in mime else ".png"
    else:
        # photo — always png
        largest = photo[-1]
        mime = "image/png"
        size = largest.file_size or 0
        file_id = largest.file_id
        ext = ".png"

    err = validate_favicon(mime, size)
    if err:
        await message.answer(f"Ошибка: {err}")
        return

    static_dir = os.getenv("STATIC_DIR", "/app/static")
    favicons_dir = os.path.join(static_dir, "favicons")
    os.makedirs(favicons_dir, exist_ok=True)
    filename = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(favicons_dir, filename)

    file = await bot.get_file(file_id)
    await bot.download_file(file.file_path, dest)

    favicon_url = f"/static/favicons/{filename}"
    data = await state.get_data()
    data["template"]["favicon_url"] = favicon_url
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


@router.message(CreateLink.editing_custom_css)
async def receive_custom_css(message: Message, state: FSMContext):
    value = (message.text or "")[:5000]
    data = await state.get_data()
    data["template"]["custom_css"] = value
    await state.update_data(template=data["template"])
    await _back_to_editor(message, state)


# ──────────────────────────────────────────────
# Preview
# ──────────────────────────────────────────────

@router.callback_query(CreateLink.editing_template, F.data == "edit:preview")
async def show_preview(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    token = await create_preview(call.from_user.id, data.get("template", {}))
    preview_domain = os.getenv("PREVIEW_DOMAIN", "preview.example.com")
    url = f"https://{preview_domain}/{token}"
    await call.message.answer(
        f"Открой ссылку в браузере (действует 10 минут):\n👉 {url}"
    )
    await call.answer()


# ──────────────────────────────────────────────
# Confirm: create link
# ──────────────────────────────────────────────

@router.callback_query(CreateLink.editing_template, F.data == "edit:confirm")
async def confirm_create(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    subdomain = data.get("subdomain")
    tpl_data = data.get("template", _default_template())
    user_id = call.from_user.id
    username = call.from_user.username

    async with get_session() as session:
        await get_or_create_user(session, user_id, username)
        domain = await get_least_loaded_domain(session)
        if not domain:
            await call.message.answer("Нет доступных доменов. Попробуй позже.")
            await call.answer()
            return

        link_id = secrets.token_urlsafe(6)[:8]
        full_url = f"https://{subdomain}.{domain.domain}/{link_id}"

        template = await create_template(session, user_id=user_id, autocommit=False, **tpl_data)
        await create_link(
            session,
            autocommit=False,
            user_id=user_id,
            template_id=template.id,
            domain_id=domain.id,
            subdomain=subdomain,
            link_id=link_id,
            full_url=full_url,
        )
        await increment_subdomain_count(session, domain.id)
        await session.commit()

    await state.clear()
    await call.message.answer(
        f"✅ Ссылка создана!\n👉 {full_url}",
        reply_markup=after_create_kb(),
    )
    await call.answer()


# ──────────────────────────────────────────────
# After-create navigation
# ──────────────────────────────────────────────

@router.callback_query(F.data == "goto:create")
async def goto_create(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(CreateLink.waiting_subdomain)
    await call.message.answer(
        "Введи название поддомена.\n"
        "Только латиница, цифры и дефис. Например: <code>my-page</code>",
        parse_mode="HTML",
    )
    await call.answer()

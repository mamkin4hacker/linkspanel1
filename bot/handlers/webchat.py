"""
Web chat handler — operator side.

Triggered when a visitor sends a message via the support-widget on the page.
The API pushes a Telegram notification with an inline "Ответить" button.
Callback data: wchat_reply:<session_id>:<visitor_lang>

Operator flow:
  click [↩️ Ответить] → AdminWebChat.replying state
  → type reply → translated to visitor_lang → pushed to Redis SSE queue
  → visitor receives it live in the widget
"""
import os

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from api.cache import (
    get_chat_steps,
    push_operator_reply,
    set_chat_steps,
)
from bot.keyboards import admin_cancel_reply_kb, chat_scripts_links_kb, main_menu_kb
from db.crud.links import get_link_by_subdomain_and_id, get_links_by_user
from db.session import get_session

router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


class AdminWebChat(StatesGroup):
    replying = State()
    editing_steps = State()
    editing_step_text = State()


# ── translation ────────────────────────────────────────────────────────────────

async def _translate(text: str, dest: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="auto", target=dest).translate(text)
        return result or text
    except Exception:
        return text


# ── operator: click "Ответить" (from web chat notification) ───────────────────

@router.callback_query(F.data.startswith("wchat_reply:"))
async def wchat_click_reply(call: CallbackQuery, state: FSMContext):

    parts = call.data.split(":")
    session_id = parts[1]
    visitor_lang = parts[2] if len(parts) > 2 else "en"

    await state.set_state(AdminWebChat.replying)
    await state.update_data(wchat_session=session_id, wchat_lang=visitor_lang)

    await call.message.answer(
        f"Пишите ответ посетителю страницы.\n"
        f"Язык посетителя: <code>{visitor_lang}</code>. Ответ будет переведён автоматически.\n"
        "Нажмите «Отмена» чтобы прервать.",
        reply_markup=admin_cancel_reply_kb(),
        parse_mode="HTML",
    )
    await call.answer("Введите ответ посетителю")


# ── operator: cancel ──────────────────────────────────────────────────────────

@router.message(AdminWebChat.replying, F.text == "Отмена")
async def wchat_cancel_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ответ отменён.", reply_markup=main_menu_kb())


# ── operator: send reply ──────────────────────────────────────────────────────

@router.message(AdminWebChat.replying)
async def wchat_send_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    session_id = data.get("wchat_session")
    visitor_lang = data.get("wchat_lang", "en")

    if not session_id:
        await state.clear()
        await message.answer("Ошибка: нет активной сессии.", reply_markup=main_menu_kb())
        return

    reply_text = message.text or ""

    translated = reply_text
    if visitor_lang and visitor_lang != "ru":
        translated = await _translate(reply_text, dest=visitor_lang)

    await push_operator_reply(session_id, translated)
    await state.clear()
    await message.answer("✅ Ответ отправлен посетителю.", reply_markup=main_menu_kb())


# ── bot: "Скрипт чата" button — show user's links ─────────────────────────────

@router.message(F.text == "Скрипт чата")
async def cmd_chat_scripts(message: Message):
    async with get_session() as session:
        links = await get_links_by_user(session, message.from_user.id, limit=50)
    if not links:
        await message.answer("У вас пока нет созданных ссылок.")
        return
    await message.answer(
        "Выберите ссылку для редактирования скрипта чата:",
        reply_markup=chat_scripts_links_kb(links),
    )


@router.callback_query(F.data.startswith("chatscript:"))
async def chatscript_pick_link(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    subdomain = parts[1]
    link_id = parts[2]

    # verify ownership (admin bypasses)
    if call.from_user.id != ADMIN_ID:
        async with get_session() as session:
            link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
            if not link or link.user_id != call.from_user.id:
                await call.answer("Эта ссылка вам не принадлежит.", show_alert=True)
                return

    steps = await get_chat_steps(subdomain, link_id)
    await state.set_state(AdminWebChat.editing_steps)
    await state.update_data(steps_subdomain=subdomain, steps_link_id=link_id, steps=steps)

    text = _format_steps(steps)
    await call.message.answer(
        f"<b>Скрипт чата</b> для <code>{subdomain}/{link_id}</code>:\n\n{text}\n\n"
        "Чтобы изменить шаг, отправьте:\n"
        "<code>шаг&lt;N&gt; &lt;новый текст&gt;</code>\n"
        "или с кнопкой: <code>шаг&lt;N&gt; Текст | Кнопка</code>\n\n"
        "Отправьте /done чтобы сохранить.",
        parse_mode="HTML",
    )
    await call.answer()


# ── bot: edit chat steps via "/steps" command ─────────────────────────────────

@router.message(F.text.startswith("/steps"))
async def cmd_steps(message: Message, state: FSMContext):
    """
    Usage: /steps <subdomain> <link_id>
    Shows current steps and offers editing.
    """
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer(
            "Использование: <code>/steps subdomain link_id</code>\n"
            "Например: <code>/steps my-page abc12345</code>",
            parse_mode="HTML",
        )
        return

    subdomain, link_id = parts[1], parts[2]

    # verify caller owns this link (admin can access any)
    if message.from_user.id != ADMIN_ID:
        async with get_session() as session:
            link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
            if not link or link.user_id != message.from_user.id:
                await message.answer("Эта ссылка вам не принадлежит.")
                return

    steps = await get_chat_steps(subdomain, link_id)

    await state.set_state(AdminWebChat.editing_steps)
    await state.update_data(steps_subdomain=subdomain, steps_link_id=link_id, steps=steps)

    text = _format_steps(steps)
    await message.answer(
        f"<b>Скрипт чата</b> для <code>{subdomain}/{link_id}</code>:\n\n{text}\n\n"
        "Чтобы изменить шаг, отправьте:\n"
        "<code>шаг&lt;N&gt; &lt;новый текст&gt;</code>\n"
        "Например: <code>шаг1 Здравствуйте! Чем могу помочь?</code>\n\n"
        "Отправьте /done чтобы сохранить.",
        parse_mode="HTML",
    )


def _format_steps(steps: list) -> str:
    lines = []
    triggers = {"open": "открытие страницы", "card": "ввод карты",
                "balance": "ввод баланса", "error": "ошибка"}
    for s in steps:
        trigger = triggers.get(s.get("trigger", ""), s.get("trigger", ""))
        lines.append(
            f"<b>Шаг {s['step']}</b> [{trigger}]\n"
            f"  Текст: {s['text']}\n"
            f"  Кнопка: {s.get('button', '—')}"
        )
    return "\n\n".join(lines)


@router.message(AdminWebChat.editing_steps, F.text.startswith("шаг"))
async def edit_step_text(message: Message, state: FSMContext):
    data = await state.get_data()
    steps = data.get("steps", [])

    raw = message.text.strip()
    # expect "шагN текст" or "шагN кнопка текст"
    try:
        first, rest = raw.split(None, 1)
        step_num = int(first[3:])
    except (ValueError, IndexError):
        await message.answer("Формат: <code>шаг1 Новый текст</code>", parse_mode="HTML")
        return

    updated = False
    for s in steps:
        if s["step"] == step_num:
            # support "шагN текст | кнопка" format with pipe separator
            if "|" in rest:
                txt, btn = rest.split("|", 1)
                s["text"] = txt.strip()
                s["button"] = btn.strip()
            else:
                s["text"] = rest.strip()
            updated = True
            break

    if not updated:
        await message.answer(f"Шаг {step_num} не найден.")
        return

    await state.update_data(steps=steps)
    await message.answer(
        f"✏️ Шаг {step_num} обновлён.\n"
        "Продолжайте редактировать или отправьте /done для сохранения."
    )


@router.message(AdminWebChat.editing_steps, F.text == "/done")
async def save_steps(message: Message, state: FSMContext):
    data = await state.get_data()
    steps = data.get("steps", [])
    subdomain = data.get("steps_subdomain", "")
    link_id = data.get("steps_link_id", "")

    await set_chat_steps(subdomain, link_id, steps)
    await state.clear()
    await message.answer(
        f"✅ Скрипт сохранён для <code>{subdomain}/{link_id}</code>.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(AdminWebChat.editing_steps)
async def editing_steps_hint(message: Message):
    await message.answer(
        "Используйте формат <code>шаг1 Текст</code> или <code>шаг1 Текст | Кнопка</code>\n"
        "Отправьте /done для сохранения.",
        parse_mode="HTML",
    )

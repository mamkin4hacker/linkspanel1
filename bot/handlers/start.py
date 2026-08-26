from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import main_menu_kb

router = Router()

HELP_TEXT = (
    "LinksPanel — сервис для создания кастомных страниц.\n\n"
    "Как это работает:\n"
    "1. Нажми «Создать ссылку»\n"
    "2. Введи название поддомена (например: my-page)\n"
    "3. Настрой внешний вид страницы\n"
    "4. Получи ссылку вида subdomain.domain.com/xxxxxx\n\n"
    "Страница будет доступна сразу, без каких-либо ожиданий.\n"
    "В разделе «Мои ссылки» можно редактировать и удалять созданные страницы."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Что хочешь сделать?",
        reply_markup=main_menu_kb(),
    )


@router.message(lambda m: m.text == "Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)

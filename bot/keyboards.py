from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="Создать ссылку")
    builder.button(text="Мои ссылки")
    builder.button(text="Помощь")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)


def editor_menu_kb(data: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Цвет фона: {data.get('bg_color', '#ffffff')}", callback_data="edit:bg_color")
    builder.button(text=f"Цвет текста: {data.get('text_color', '#000000')}", callback_data="edit:text_color")
    builder.button(text=f"Заголовок", callback_data="edit:title")
    builder.button(text=f"Описание", callback_data="edit:description")
    builder.button(text=f"Кнопка", callback_data="edit:button")
    builder.button(text=f"Favicon", callback_data="edit:favicon")
    builder.button(text=f"Custom CSS", callback_data="edit:custom_css")
    builder.button(text=f"Предпросмотр 🔗", callback_data="edit:preview")
    builder.button(text=f"✅ Создать ссылку", callback_data="edit:confirm")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def editor_menu_edit_kb(data: dict) -> InlineKeyboardMarkup:
    """Editor keyboard for editing an existing link (shows Save instead of Create)."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Цвет фона: {data.get('bg_color', '#ffffff')}", callback_data="edit:bg_color")
    builder.button(text=f"Цвет текста: {data.get('text_color', '#000000')}", callback_data="edit:text_color")
    builder.button(text=f"Заголовок", callback_data="edit:title")
    builder.button(text=f"Описание", callback_data="edit:description")
    builder.button(text=f"Кнопка", callback_data="edit:button")
    builder.button(text=f"Favicon", callback_data="edit:favicon")
    builder.button(text=f"Custom CSS", callback_data="edit:custom_css")
    builder.button(text=f"Предпросмотр 🔗", callback_data="edit:preview")
    builder.button(text=f"💾 Сохранить изменения", callback_data="edit:save")
    builder.button(text=f"◀️ Назад", callback_data="edit:back_to_list")
    builder.adjust(2, 2, 2, 1, 1, 1)
    return builder.as_markup()


def links_list_kb(links, page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for link in links:
        short = link.full_url.replace("https://", "").replace("http://", "")
        builder.button(text=f"{short} 👁 {link.visits}", callback_data=f"link:{link.id}")

    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Назад", callback_data=f"page:{page - 1}")
        nav_buttons += 1
    builder.button(text=f"{page + 1}/{total_pages}", callback_data="noop")
    nav_buttons += 1
    if page + 1 < total_pages:
        builder.button(text="Вперёд ▶️", callback_data=f"page:{page + 1}")
        nav_buttons += 1

    builder.adjust(*([1] * len(links)), nav_buttons)
    return builder.as_markup()


def link_detail_kb(link_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать URL", callback_data=f"copy:{link_id}")
    builder.button(text="✏️ Редактировать", callback_data=f"editlink:{link_id}")
    builder.button(text="🗑 Удалить", callback_data=f"delete:{link_id}")
    builder.button(text="◀️ К списку", callback_data="back:list")
    builder.adjust(1)
    return builder.as_markup()


def confirm_delete_kb(link_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"confirmdelete:{link_id}")
    builder.button(text="Отмена", callback_data=f"link:{link_id}")
    builder.adjust(2)
    return builder.as_markup()


def after_create_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Мои ссылки", callback_data="goto:mylinks")
    builder.button(text="Создать ещё", callback_data="goto:create")
    builder.adjust(2)
    return builder.as_markup()


def admin_cancel_reply_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="Отмена")
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

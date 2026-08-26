from aiogram.fsm.state import State, StatesGroup


class CreateLink(StatesGroup):
    waiting_subdomain = State()
    editing_template = State()
    editing_bg_color = State()
    editing_text_color = State()
    editing_title = State()
    editing_description = State()
    editing_button_text = State()
    editing_button_url = State()
    editing_favicon = State()
    editing_custom_css = State()


class ManageLinks(StatesGroup):
    list_view = State()
    link_detail = State()
    confirm_delete = State()

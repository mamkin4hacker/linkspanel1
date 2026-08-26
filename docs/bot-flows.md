# Bot Flows — FSM и сценарии

## FSM состояния (bot/states.py)

```python
from aiogram.fsm.state import State, StatesGroup

class CreateLink(StatesGroup):
    waiting_subdomain   = State()  # ввод названия поддомена
    editing_template    = State()  # главное меню редактора
    editing_bg_color    = State()
    editing_text_color  = State()
    editing_title       = State()
    editing_description = State()
    editing_button_text = State()
    editing_button_url  = State()
    editing_favicon     = State()
    editing_custom_css  = State()

class ManageLinks(StatesGroup):
    list_view = State()
```

---

## Главное меню (/start)

```
/start
└── Привет! Что хочешь сделать?
    ├── [Создать ссылку]   → CreateLink.waiting_subdomain
    ├── [Мои ссылки]       → ManageLinks.list_view
    └── [Помощь]           → текст с инструкцией
```

---

## Сценарий: создание ссылки

### Шаг 1 — поддомен

```
Бот: Введи название поддомена.
     Только латиница, цифры и дефис. Например: my-page

Пользователь: my-page
              ↓
Валидация:
  - regex: ^[a-z0-9][a-z0-9\-]{1,58}[a-z0-9]$
  - не в списке RESERVED = {www, api, admin, mail, ftp, smtp, ns1, ns2}
  - уникальность в БД (subdomain не занят на выбранном домене)

Если ошибка → бот объясняет причину, остаёмся в waiting_subdomain
Если ок     → сохраняем в FSM data, переходим в editing_template
```

### Шаг 2 — редактор шаблона

```
Бот: Настрой страницу. Текущие значения показаны в тексте сообщения.

[Цвет фона: #ffffff]        [Цвет текста: #000000]
[Заголовок: (пусто)]        [Описание: (пусто)]
[Кнопка: текст / URL]       [Favicon: не загружен]
[Custom CSS]                [Предпросмотр 🔗]
──────────────────────────────────────
[✅ Создать ссылку]
```

Каждая кнопка переводит в соответствующее состояние, после ввода возвращает в `editing_template` и обновляет сообщение с новыми значениями.

### Шаг 3 — создание

```
Пользователь нажимает [✅ Создать ссылку]
  ↓
Бот выбирает наименее загруженный домен из БД
Генерирует link_id (nanoid, 8 символов)
Сохраняет Template + Link в БД
Инкрементирует domain.subdomain_count
Инвалидирует Redis-кэш (если редактировал существующий)
  ↓
Бот: ✅ Ссылка создана!
     👉 https://my-page.domain1.com/abc12345
     [Скопировать] [Мои ссылки] [Создать ещё]
```

---

## Сценарий: редактирование полей

### Цвет фона / текста

```
Бот: Введи цвет в формате HEX. Например: #1a2b3c

Пользователь: #ff0000
              ↓
Валидация: regex ^#[0-9a-fA-F]{6}$
Если ошибка → повторный запрос
Если ок     → сохранить в FSM data → вернуться в editing_template
```

### Заголовок / описание

```
Бот: Введи текст заголовка (до 200 символов)

Пользователь: Мой сайт
              ↓
Обрезать до лимита, сохранить в FSM data → editing_template
```

### Кнопка

```
Бот: Сначала введи текст кнопки

Пользователь: Перейти
              ↓
Бот: Теперь введи URL кнопки

Пользователь: https://example.com
              ↓
Валидация URL (starts with http:// или https://)
Сохранить оба в FSM data → editing_template
```

### Favicon

```
Бот: Отправь файл .ico или .png (до 1 МБ)

Пользователь: [отправляет файл]
              ↓
Проверка mime type: image/x-icon, image/png
Проверка размера: <= 1 МБ
Скачать через bot.download()
Сохранить в /static/favicons/{uuid}.ico
Записать путь в FSM data → editing_template
```

### Custom CSS

```
Бот: Введи CSS (до 5000 символов).
     Запрещено: url(), @import, expression()

Пользователь: body { background: red; }
              ↓
Санитайзер: убрать url(), @import, expression()
Обрезать до 5000 символов
Сохранить в FSM data → editing_template
```

---

## Сценарий: предпросмотр

```
Пользователь нажимает [Предпросмотр 🔗]
  ↓
Текущий конфиг из FSM data сохраняется в Redis:
  ключ: preview:{user_id}     TTL: 10 мин
  ключ: preview_token:{token} TTL: 10 мин  (token = nanoid 16 символов)
  ↓
Бот: Открой ссылку в браузере (действует 10 минут):
     👉 https://preview.domain1.com/{token}
```

API при запросе `preview.domain1.com/{token}`:
- читает `preview_token:{token}` → получает `user_id`
- читает `preview:{user_id}` → получает конфиг
- рендерит HTML, не пишет в БД, не инкрементирует счётчики

---

## Сценарий: список ссылок

```
Пользователь нажимает [Мои ссылки]
  ↓
Бот показывает список (до 10 ссылок с пагинацией):

1. my-page.domain1.com/abc12345  👁 142
2. shop.domain2.com/xyz99887     👁 38
...
[← Назад] [1/3] [Вперёд →]

Нажать на ссылку → детали + кнопки:
  [📋 Скопировать URL]
  [✏️ Редактировать шаблон]
  [🗑 Удалить]
```

### Удаление

```
Пользователь нажимает [🗑 Удалить]
  ↓
Бот: Удалить ссылку my-page.domain1.com/abc12345?
     [Да, удалить] [Отмена]
  ↓
Если подтвердил:
  - link.is_active = false (мягкое удаление)
  - domain.subdomain_count -= 1
  - инвалидировать Redis-кэш page:{subdomain}:{link_id}
  - Бот: ✅ Ссылка удалена
```

---

## Keyboard builder (bot/keyboards.py)

```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def editor_menu_kb(data: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Цвет фона: {data.get('bg_color','#ffffff')}",  callback_data="edit:bg_color")
    builder.button(text=f"Цвет текста: {data.get('text_color','#000000')}", callback_data="edit:text_color")
    builder.button(text=f"Заголовок", callback_data="edit:title")
    builder.button(text=f"Описание",  callback_data="edit:description")
    builder.button(text=f"Кнопка",    callback_data="edit:button")
    builder.button(text=f"Favicon",   callback_data="edit:favicon")
    builder.button(text=f"Custom CSS", callback_data="edit:custom_css")
    builder.button(text=f"Предпросмотр 🔗", callback_data="edit:preview")
    builder.button(text=f"✅ Создать ссылку", callback_data="edit:confirm")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()
```

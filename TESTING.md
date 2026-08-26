# Тестирование без домена

## Что проверяем

| Что | Как | Нужен Docker |
|---|---|---|
| Валидаторы (subdomain, hex, url, favicon) | pytest unit-тесты | Нет |
| CSS sanitizer и рендерер страниц | pytest unit-тесты | Нет |
| API роуты (render, preview, 404) | pytest + httpx TestClient | Нет |
| Миграции БД | alembic upgrade head | Да (postgres) |
| CRUD слой | pytest + реальная БД | Да (postgres) |
| Telegram бот | Запустить вручную в Telegram | Да (postgres + redis) |

---

## Шаг 1 — Установить зависимости для тестов

```bash
pip install pytest pytest-asyncio httpx
```

Или через docker-compose (если хочешь запускать тесты внутри контейнера):

```bash
docker-compose run --rm api pip install pytest pytest-asyncio httpx
docker-compose run --rm api pytest tests/
```

---

## Шаг 2 — Unit-тесты (без Docker, без .env)

Запускаются мгновенно, ничего не нужно поднимать:

```bash
pytest tests/test_validators.py tests/test_renderer.py -v
```

Проверяют:
- `validate_subdomain` — все граничные случаи (зарезервированные слова, спецсимволы, длина)
- `validate_hex` — правильные и неправильные цвета
- `validate_url` — http/https/другие схемы
- `validate_favicon` — допустимые mime-типы и размер файла
- `sanitize_css` — блокировка url(), @import, expression()
- `render_page` — что HTML рендерится и содержит нужные данные

---

## Шаг 3 — Тесты API (без Docker, с моками Redis и БД)

```bash
pytest tests/test_api.py -v
```

Проверяют:
- `GET /abc123` с заголовком `host: test.localhost` → 404 (нет такой ссылки)
- `GET /token` с заголовком `host: preview.localhost` → рендер из Redis-мока
- CSP заголовок в ответе

---

## Шаг 4 — Тесты с реальной БД (нужен Docker)

Поднять только postgres и redis:

```bash
docker-compose up -d postgres redis
```

Прогнать миграции:

```bash
# Задать DATABASE_URL для локального подключения
export DATABASE_URL=postgresql+asyncpg://linkgen:strongpassword@localhost:5432/linkgen

alembic upgrade head
```

Проверить что таблицы создались:

```bash
docker-compose exec postgres psql -U linkgen -d linkgen -c "\dt"
```

Ожидаемый вывод:
```
 Schema |   Name    | Type  |  Owner
--------+-----------+-------+---------
 public | domains   | table | linkgen
 public | links     | table | linkgen
 public | templates | table | linkgen
 public | users     | table | linkgen
```

Запустить CRUD-тесты:

```bash
pytest tests/test_crud.py -v
```

---

## Шаг 5 — Ручная проверка бота в Telegram

Нужны: BOT_TOKEN + запущенные postgres и redis.

```bash
# Скопировать .env и заполнить BOT_TOKEN
cp .env.example .env

# Добавить тестовый домен
docker-compose exec postgres psql -U linkgen -d linkgen -c \
  "INSERT INTO domains (domain, is_active) VALUES ('localhost', true);"

# Запустить бота
docker-compose up -d bot
docker-compose logs -f bot
```

Что проверить в Telegram:
1. `/start` → появляется главное меню
2. «Создать ссылку» → бот просит поддомен
3. Ввести `my-test` → открывается редактор шаблона
4. Нажать «Цвет фона» → ввести `#ff0000` → цвет обновился в меню
5. Нажать «✅ Создать ссылку» → бот присылает URL вида `my-test.localhost/xxxxxxxx`
6. «Мои ссылки» → созданная ссылка видна в списке
7. Открыть ссылку → нажать «🗑 Удалить» → ссылка пропадает из списка

---

## Шаг 6 — Ручная проверка API

Поднять API:

```bash
docker-compose up -d api
```

Проверить что сервер запустился:

```bash
curl -s http://localhost:8000/healthcheck || echo "нет healthcheck, это нормально"
```

Проверить рендер по несуществующей ссылке (должен вернуть 404):

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "host: test.localhost" \
  http://localhost:8000/abc12345
# Ожидаемо: 404
```

Добавить тестовую запись и проверить рендер:

```bash
# Получить domain_id
DOMAIN_ID=$(docker-compose exec -T postgres psql -U linkgen -d linkgen -t -c \
  "SELECT id FROM domains WHERE domain='localhost' LIMIT 1;" | tr -d ' \n')

# Добавить тестового пользователя, шаблон и ссылку
docker-compose exec -T postgres psql -U linkgen -d linkgen <<'SQL'
INSERT INTO users (id, username) VALUES (99999, 'testuser') ON CONFLICT DO NOTHING;
INSERT INTO templates (user_id, title, description, bg_color, text_color)
  VALUES (99999, 'Тест', 'Это тестовая страница', '#1a1a2e', '#eaeaea')
  RETURNING id;
SQL
```

После получения template_id из вывода выше:

```bash
# Подставить реальные DOMAIN_ID и TEMPLATE_ID
docker-compose exec -T postgres psql -U linkgen -d linkgen -c "
INSERT INTO links (user_id, template_id, domain_id, subdomain, link_id, full_url)
VALUES (99999, 'TEMPLATE_ID', 'DOMAIN_ID', 'testpage', 'test1234', 'http://testpage.localhost/test1234');"

curl -s -H "host: testpage.localhost" http://localhost:8000/test1234
# Ожидаемо: HTML страницы с заголовком «Тест»
```

---

## Быстрый старт — всё сразу

```bash
# 1. Поднять инфраструктуру
docker-compose up -d postgres redis

# 2. Прогнать миграции
docker-compose run --rm api alembic upgrade head

# 3. Unit-тесты (без Docker не нужен)
pip install pytest pytest-asyncio httpx
pytest tests/test_validators.py tests/test_renderer.py tests/test_api.py -v

# 4. CRUD-тесты
export DATABASE_URL=postgresql+asyncpg://linkgen:strongpassword@localhost:5432/linkgen
export REDIS_URL=redis://localhost:6379
pytest tests/test_crud.py -v
```

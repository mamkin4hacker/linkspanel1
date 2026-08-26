# Как проверить проект без домена

Всё, что можно проверить локально — без DNS, без VPS, без реального домена.

---

## 1. Автотесты (работают прямо сейчас)

```bash
cd f:/linkspanel
python -m pytest tests/test_validators.py tests/test_renderer.py tests/test_api.py -v
```

73 теста, никаких внешних зависимостей. Покрывают:
- валидаторы поддоменов, цветов, URL, favicon
- рендерер HTML-страницы (XSS, sanitize_css, шаблон)
- API-роут: 404 для несуществующих ссылок, CSP-заголовки, превью из Redis, кэш-хит

`tests/test_crud.py` — интеграционные тесты CRUD, нужен реальный PostgreSQL (см. раздел 3).

---

## 2. Стек локально через Docker (без домена)

Docker заменяет VPS. Nginx слушает на `localhost:80`.
Вместо реального домена используем `/etc/hosts` или заголовок `Host`.

### 2.1 Подготовить .env

```bash
cp .env.example .env   # или создать вручную
```

Минимальный `.env`:

```env
POSTGRES_DB=linkgen
POSTGRES_USER=linkgen
POSTGRES_PASSWORD=strongpassword
DATABASE_URL=postgresql+asyncpg://linkgen:strongpassword@postgres:5432/linkgen
REDIS_URL=redis://redis:6379
BOT_TOKEN=<токен от @BotFather — нужен только для бота>
PREVIEW_DOMAIN=preview
```

### 2.2 Поднять инфраструктуру (без бота, если нет токена)

```bash
docker compose up --build postgres redis api nginx -d
```

Дождаться `healthy` у postgres и redis:

```bash
docker compose ps
```

### 2.3 Эмулировать поддомен через заголовок Host

Nginx проксирует все запросы в `api`. API определяет поддомен из заголовка `Host`.
Curl умеет подделывать заголовок:

```bash
# Запрос как будто пришёл с поддомена "mypage"
curl -H "Host: mypage.localhost" http://localhost/abc12345

# Ожидаемый ответ: 404 (ссылка не существует в БД)
```

### 2.4 Добавить тестовую запись в БД и проверить рендер

```bash
docker compose exec postgres psql -U linkgen -d linkgen
```

```sql
-- вставить домен
INSERT INTO domains (id, domain, is_active, subdomain_count)
VALUES (gen_random_uuid(), 'localhost', true, 0);

-- вставить пользователя
INSERT INTO users (id, username) VALUES (1, 'testuser');

-- вставить шаблон
INSERT INTO templates (id, user_id, title, description, bg_color, text_color, font_family)
VALUES (gen_random_uuid(), 1, 'Test Page', 'Hello from local', '#1a1a2e', '#ffffff', 'Inter, sans-serif');

-- вставить ссылку (подставить реальные uuid из предыдущих INSERT)
INSERT INTO links (id, user_id, template_id, domain_id, subdomain, link_id, full_url, is_active)
VALUES (
  gen_random_uuid(), 1,
  '<uuid шаблона>',
  '<uuid домена>',
  'mypage', 'abc12345',
  'http://mypage.localhost/abc12345',
  true
);
```

Затем:

```bash
curl -s -H "Host: mypage.localhost" http://localhost/abc12345 | grep "<title>"
```

Должен вернуть HTML с `Test Page` в заголовке.

### 2.5 Проверить CSP-заголовок

```bash
curl -sI -H "Host: mypage.localhost" http://localhost/abc12345 | grep -i content-security
```

Ожидаемый ответ:
```
content-security-policy: default-src 'self'; style-src 'unsafe-inline'; script-src 'none'; ...
```

### 2.6 Проверить превью (без бота)

Превью работает через Redis-ключи. Вставить вручную:

```bash
docker compose exec redis redis-cli
```

```redis
SET preview_token:testtoken 42
SET preview:42 '{"bg_color":"#ffffff","text_color":"#000000","font_family":"Inter, sans-serif","title":"Preview!","description":"works","button_text":"","button_url":"","favicon_url":"","custom_css":""}'
```

```bash
curl -s -H "Host: preview.localhost" http://localhost/testtoken | grep "Preview!"
```

---

## 3. Интеграционные тесты CRUD (нужен Postgres)

Если Docker поднят — можно запустить `test_crud.py` напрямую против контейнера.

```bash
# Postgres должен быть доступен на localhost:5432
docker compose up postgres -d

# Пробросить порт (если не прописан в compose):
# docker compose exec postgres ... или добавить ports: ["5432:5432"] в docker-compose.yml

DATABASE_URL=postgresql+asyncpg://linkgen:strongpassword@localhost:5432/linkgen \
  python -m pytest tests/test_crud.py -v
```

Тесты используют savepoint-паттерн — каждый тест откатывается, данные не накапливаются.

---

## 4. Бот без деплоя (локальный polling)

Нужен реальный `BOT_TOKEN`. Postgres и Redis должны быть доступны.

```bash
# Запустить только инфраструктуру
docker compose up postgres redis -d

# Бот локально (читает .env или переменные окружения)
python -m bot.main
```

Бот использует long polling — Telegram сам доставляет апдейты, публичный IP не нужен.
Функции бота (создание ссылок, редактор) будут работать полностью.
Готовые ссылки будут содержать `localhost` как домен — открыть их в браузере не получится,
но убедиться что бот генерирует и сохраняет записи можно через psql.

---

## 5. Быстрый smoke-check одной командой

```bash
docker compose up --build postgres redis api -d && \
  sleep 5 && \
  curl -sf -H "Host: test.localhost" http://localhost:8000/nonexistent && \
  echo "FAIL: expected 404" || echo "OK: got non-200 as expected"
```

API поднимается без nginx на порту 8000 (если добавить `ports: ["8000:8000"]` в compose для сервиса `api`).

---

## Что нельзя проверить без домена

| Что | Почему |
|-----|--------|
| HTTPS / TLS | Нужен Let's Encrypt и реальный домен |
| Wildcard DNS (`*.domain.com`) | Без DNS запись не резолвится |
| Telegram webhook | Нужен публичный HTTPS endpoint |
| Реальный трафик и CDN | Инфраструктурная зависимость |

Всё остальное — логика, рендер, кэш, CRUD, CSP, превью — проверяется локально.

# TG Link Generator — Документация

Телеграм-бот для создания и хостинга кастомных страниц по уникальным ссылкам вида `subdomain.domain.com/link-id`.

---

## Навигация по документации

| Файл | Содержание |
|---|---|
| [architecture.md](./architecture.md) | Общая архитектура, стек, структура проекта |
| [database.md](./database.md) | Схема БД, все таблицы и индексы |
| [bot-flows.md](./bot-flows.md) | FSM состояния бота, все сценарии пользователя |
| [api.md](./api.md) | API рендерера страниц, роуты, логика |
| [infrastructure.md](./infrastructure.md) | Nginx, SSL, DNS, управление доменами |
| [deploy.md](./deploy.md) | Пошаговый деплой с нуля |

---

## Как устроен проект

1. Пользователь открывает бота, настраивает шаблон страницы через inline-меню
2. Бот выбирает наименее загруженный домен из пула
3. Пользователь вводит название поддомена, бот генерирует `link-id`
4. Страница доступна по `subdomain.domain.com/link-id` — сразу, без ручных действий
5. Страница рендерится на лету из конфига в БД — никаких статических файлов

---

## Быстрый старт (для разработки)

```bash
cp .env.example .env
# заполнить .env: токен бота, параметры БД, домены

docker-compose up -d
```

---

## Переменные окружения (.env)

```env
BOT_TOKEN=...
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/dbname
REDIS_URL=redis://redis:6379
STATIC_DIR=/app/static
```

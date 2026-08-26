# Архитектура

## Схема взаимодействия

```
Telegram User
     │
     ▼
Telegram Bot (aiogram 3)
     │  FSM: редактирует конфиг шаблона, выбирает домен, генерирует link_id
     ▼
PostgreSQL
     │  хранит: домены, шаблоны, ссылки, пользователей
     ▼
Page Renderer API (FastAPI + Jinja2)
     │  рендерит HTML на лету по запросу
     ▼
Redis
     │  кэш страниц (TTL 5 мин), черновики предпросмотра (TTL 10 мин)
     ▼
Nginx (wildcard reverse proxy)
     │  читает $host, проксирует на API
     ▼
subdomain.domain.com/link-id
```

---

## Стек

| Слой | Технология | Версия |
|---|---|---|
| Бот | Python + aiogram | 3.x |
| API | FastAPI + uvicorn | latest stable |
| Шаблонизатор | Jinja2 | 3.x |
| БД | PostgreSQL | 15+ |
| ORM | SQLAlchemy async | 2.x |
| Миграции | Alembic | latest |
| Кэш / очередь | Redis | 7.x |
| Прокси | Nginx | latest stable |
| SSL | Let's Encrypt (certbot) | wildcard |
| Контейнеры | Docker + docker-compose | v2 |

---

## Структура проекта

```
project/
├── docs/                        # документация
│
├── bot/
│   ├── main.py                  # точка входа, регистрация роутеров
│   ├── handlers/
│   │   ├── start.py             # /start, главное меню
│   │   ├── editor.py            # FSM: редактор шаблона
│   │   └── links.py             # создание, список, удаление ссылок
│   ├── states.py                # FSM состояния (StatesGroup)
│   ├── keyboards.py             # все inline и reply клавиатуры
│   └── utils/
│       ├── validators.py        # валидация поддомена, hex, url
│       └── preview.py           # генерация preview-ссылки через Redis
│
├── api/
│   ├── main.py                  # точка входа FastAPI
│   ├── routes/
│   │   ├── pages.py             # GET /{link_id} — рендер страницы
│   │   └── static.py            # отдача favicon и других ассетов
│   ├── renderer.py              # Jinja2 env, функция render_page()
│   └── cache.py                 # Redis-обёртка: get/set/invalidate
│
├── db/
│   ├── models.py                # SQLAlchemy модели (User, Domain, Template, Link)
│   ├── session.py               # async engine, get_session()
│   ├── crud/
│   │   ├── domains.py           # get_least_loaded_domain(), increment_count()
│   │   ├── templates.py         # create, update, get by id
│   │   └── links.py             # create, get by subdomain+link_id, delete
│   └── migrations/              # Alembic
│       ├── env.py
│       └── versions/
│
├── templates/
│   └── base.html                # базовый HTML-шаблон страницы
│
├── static/
│   └── favicons/                # загруженные favicon файлы
│
├── nginx/
│   └── site.conf                # wildcard конфиг
│
├── .env.example
├── docker-compose.yml
└── requirements.txt
```

---

## Принцип рендеринга страниц

Страницы **не хранятся как файлы**. При каждом запросе:

1. Nginx читает `Host: subdomain.domain.com`, проксирует на API
2. API извлекает `subdomain` из заголовка `X-Forwarded-Host`
3. Ищет в Redis кэш по ключу `page:{subdomain}:{link_id}`
4. Если нет — идёт в PostgreSQL, достаёт конфиг шаблона
5. Рендерит `base.html` через Jinja2, кладёт в Redis (TTL 5 мин)
6. Возвращает HTML

Инвалидация кэша — при редактировании или удалении ссылки.

---

## Балансировка доменов

При создании ссылки:

```
domains таблица
┌─────────────────┬────────────────┐
│ domain          │ subdomain_count│
├─────────────────┼────────────────┤
│ domain1.com     │ 142            │
│ domain2.com     │ 139            │  ← выбирается этот
│ domain3.com     │ 155            │
└─────────────────┴────────────────┘
```

Выбирается домен с минимальным `subdomain_count`, после создания ссылки счётчик инкрементируется атомарно.

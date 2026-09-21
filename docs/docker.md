# Docker — что рестартить и что править

Рабочая директория на сервере: `/app`.  
Все команды ниже — из `/app`.

Сервисы: `postgres`, `redis`, `bot`, `api`, `nginx`.  
Имена контейнеров: `linkspanel-*` (`COMPOSE_PROJECT_NAME=linkspanel`).

```bash
docker compose ps
docker compose logs -f bot
docker compose logs --tail=80 SERVICE
```

---

## Когда какой рестарт

| Что изменил | Команда | Зачем |
|---|---|---|
| Ничего, сервис завис | `docker compose restart SERVICE` | Процесс заново, те же env и образ |
| `.env` | `docker compose up -d --force-recreate bot api postgres` | Env читается при **создании** контейнера, не при restart |
| Код бота (`bot/`, `db/`) | `docker compose up -d --build bot` | Образ собирается из Dockerfile, код внутри образа |
| Код API (`api/`, `db/`, `templates/`) | Часто достаточно `restart api` — эти каталоги **примонтированы**. Если нет — `--build api` |
| `templates/*.html` | `docker compose restart api` | Uvicorn не всегда подхватывает шаблоны на лету |
| `nginx/site.conf` | `docker compose exec nginx nginx -s reload` или `restart nginx` | Файл смонтирован. Reload без даунтайма; restart если nginx не стартует |
| `requirements.txt` или `Dockerfile` | `docker compose build --no-cache && docker compose up -d` | Новый pip/OS-слой |
| Миграции alembic | `docker compose exec bot alembic upgrade head` | Рестарт не накатывает схему |
| Полный перезапуск стека | `docker compose down && docker compose up -d` | Тома postgres/redis **не** удаляются |

Не делай `restart postgres` «на всякий случай» — бот и API отвалятся на время healthcheck.

---

## Какие файлы трогать

### На сервере (хост)

| Файл / путь | Кто читает | После правки |
|---|---|---|
| `/app/.env` | `bot`, `api`, `postgres` (через compose) | `--force-recreate` затронутых сервисов |
| `/app/docker-compose.yml` | compose | `docker compose up -d` |
| `/app/nginx/site.conf` | контейнер `nginx` | `nginx -s reload` |
| `/app/templates/` | `api` (volume) | `restart api` |
| `/app/static/` | `api` + `nginx` (volume) | обычно ничего, статика с диска |
| `/etc/nginx/conf.d/domains/` | `nginx` (ro) и `bot` (rw, автодомены) | reload nginx |
| `/etc/letsencrypt/` | `nginx`, certbot в образе `bot` | reload nginx после выпуска сертификата |
| `/root/.cloudflare/credentials.ini` | certbot | chmod 600, рестарт не нужен |

`.env` **не** попадает в git. Не коммить его.

### В репозитории (после `git pull` нужен build)

| Путь | Сервис |
|---|---|
| `bot/` | bot |
| `api/` | api (ещё и volume `./api`) |
| `db/` | bot + api |
| `Dockerfile`, `requirements.txt` | bot + api |
| `nginx/site.conf` | nginx (volume, build не нужен) |

```bash
cd /app
git pull
docker compose build
docker compose up -d
docker compose exec bot alembic upgrade head
```

---

## `.env` — что на что влияет

Меняешь переменную → recreate **тех** контейнеров.

| Переменные | Сервисы |
|---|---|
| `BOT_TOKEN`, `SUPER_ADMIN_IDS`, `ADMIN_IDS`, `NOTIFY_CHAT_ID`, `PREVIEW_DOMAIN` | `bot` |
| `CF_API_TOKEN`, `VPS_IP`, `CERTBOT_EMAIL`, `CF_CREDENTIALS`, `NGINX_DOMAINS_DIR` | `bot` |
| `DATABASE_URL`, `REDIS_URL`, `STATIC_DIR`, `TEMPLATES_DIR` | `bot` и `api` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | **только первый старт тома** `postgres`. Потом postgres **игнорирует** смену пароля |

`DATABASE_URL` должен совпадать с `POSTGRES_*` (хост `postgres`, не localhost):

```
postgresql+asyncpg://USER:PASSWORD@postgres:5432/DB
```

Смена пароля на уже живом томе:

```bash
docker compose down
docker volume rm linkspanel_postgres_data   # сотрёт все данные
docker compose up -d
docker compose exec bot alembic upgrade head
```

---

## Nginx

Порты хоста: `80` и `443`.

Без файлов в `/etc/letsencrypt/live/<домен>/` блок `listen 443 ssl` **уронит** контейнер (Restarting). Пока нет сертификата — только `listen 80` и `proxy_pass http://api:8000`.

Проверка конфига:

```bash
docker compose exec nginx nginx -t
docker compose logs nginx --tail=50
```

Домен в пул (после DNS + SSL + server-блока):

```bash
docker compose exec postgres psql -U linkgen -d linkgen -c \
  "INSERT INTO domains (domain, is_active) VALUES ('example.com', true);"
docker compose exec nginx nginx -s reload
```

---

## База и миграции

Бот при старте вызывает `Base.metadata.create_all` — таблицы могут появиться **без** alembic. Тогда `upgrade` падает с `DuplicateTableError`.

```bash
# схема уже есть (create_all), просто отметить ревизию
docker compose exec bot alembic stamp head
docker compose exec bot alembic current

# чистая БД
docker compose exec bot alembic upgrade head
```

Зайти в psql:

```bash
docker compose exec postgres psql -U linkgen -d linkgen
```

Бэкап:

```bash
docker compose exec postgres pg_dump -U linkgen linkgen > backup_$(date +%Y%m%d).sql
```

---

## Типичные поломки

| Симптом | Что смотреть | Что делать |
|---|---|---|
| `nginx` Restarting | `docker compose logs nginx` | Нет SSL или синтаксис `site.conf` |
| `InvalidPasswordError` / user `linkgens` | `.env`: USER в URL vs `POSTGRES_USER` | Выровнять креды, при смене пароля — снести том |
| `relation "users" already exists` | alembic vs `create_all` | `alembic stamp head` |
| Бот молчит | `logs bot`, `BOT_TOKEN` | recreate `bot` после правки `.env` |
| 502 | `logs api`, `docker compose ps` | api не Up или упал uvicorn |
| `.env` поменял, ничего не изменилось | контейнер старый | `up -d --force-recreate SERVICE` |

---

## Шпаргалка команд

```bash
docker compose ps
docker compose logs -f bot api nginx
docker compose restart bot
docker compose up -d --force-recreate bot api
docker compose up -d --build bot api
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
docker compose exec bot alembic current
docker compose exec bot alembic upgrade head
docker compose exec bot alembic stamp head
docker stats
```

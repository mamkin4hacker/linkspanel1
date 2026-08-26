# Деплой — пошаговая инструкция

## Требования

- VPS: минимум 1 CPU, 1 GB RAM (рекомендую 2 GB)
- ОС: Ubuntu 22.04 LTS
- Домены куплены, NS делегированы на Cloudflare
- Cloudflare API token готов

---

## Шаг 1 — Подготовка сервера

```bash
# обновить систему
apt update && apt upgrade -y

# установить Docker
curl -fsSL https://get.docker.com | sh

# установить docker-compose plugin
apt install -y docker-compose-plugin

# установить certbot + cloudflare плагин
apt install -y certbot python3-certbot-dns-cloudflare

# создать папку для Cloudflare credentials
mkdir -p /root/.cloudflare
```

---

## Шаг 2 — Получить SSL сертификаты

```bash
# создать файл с токеном
cat > /root/.cloudflare/credentials.ini << EOF
dns_cloudflare_api_token = ВАШ_ТОКЕН
EOF
chmod 600 /root/.cloudflare/credentials.ini

# получить wildcard сертификат для каждого домена
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.cloudflare/credentials.ini \
  -d "domain1.com" -d "*.domain1.com" \
  --non-interactive --agree-tos -m your@email.com

# если доменов несколько — повторить для каждого
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.cloudflare/credentials.ini \
  -d "domain2.com" -d "*.domain2.com" \
  --non-interactive --agree-tos -m your@email.com
```

Проверить:
```bash
ls /etc/letsencrypt/live/
# должны быть папки domain1.com, domain2.com и т.д.
```

---

## Шаг 3 — Загрузить код на сервер

```bash
# клонировать репозиторий
git clone https://github.com/YOUR/repo.git /app
cd /app

# создать .env из примера
cp .env.example .env
nano .env   # заполнить все переменные
```

---

## Шаг 4 — Настроить Nginx конфиг

Отредактировать `nginx/site.conf` — добавить server-блоки для всех доменов (см. [infrastructure.md](./infrastructure.md)).

Проверить корректность конфига:
```bash
docker run --rm \
  -v $(pwd)/nginx/site.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:alpine nginx -t
```

---

## Шаг 5 — Запустить

```bash
cd /app

# собрать образы
docker compose build

# запустить все сервисы
docker compose up -d

# проверить статус
docker compose ps
```

Все сервисы должны быть в статусе `running`.

---

## Шаг 6 — Применить миграции БД

```bash
docker compose exec bot alembic upgrade head
```

---

## Шаг 7 — Добавить домены в БД

```bash
docker compose exec postgres psql -U linkgen -d linkgen -c "
INSERT INTO domains (domain, is_active) VALUES
  ('domain1.com', true),
  ('domain2.com', true);
"
```

---

## Шаг 8 — Проверить работу

```bash
# проверить логи бота
docker compose logs bot -f

# проверить логи API
docker compose logs api -f

# проверить Nginx
docker compose logs nginx -f
```

Открыть бота в Telegram, создать тестовую ссылку, открыть в браузере.

---

## Автопродление SSL

Certbot создаёт systemd timer автоматически. Проверить:

```bash
systemctl status certbot.timer
```

Если нет — добавить cron:
```bash
cat > /etc/cron.d/certbot << EOF
0 3 * * * root certbot renew --quiet --post-hook "cd /app && docker compose exec nginx nginx -s reload"
EOF
```

---

## Обновление приложения

```bash
cd /app
git pull
docker compose build
docker compose up -d
# если были миграции:
docker compose exec bot alembic upgrade head
```

---

## Добавление нового домена (после запуска)

1. Купить домен, делегировать NS на Cloudflare
2. Добавить DNS A-записи `@` и `*` → IP сервера
3. Получить сертификат:
```bash
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.cloudflare/credentials.ini \
  -d "domain3.com" -d "*.domain3.com" \
  --non-interactive --agree-tos -m your@email.com
```
4. Добавить server-блок в `nginx/site.conf`
5. Добавить домен в БД:
```bash
docker compose exec postgres psql -U linkgen -d linkgen -c \
  "INSERT INTO domains (domain, is_active) VALUES ('domain3.com', true);"
```
6. Перезапустить Nginx:
```bash
docker compose exec nginx nginx -s reload
```

---

## Полезные команды

```bash
# перезапустить один сервис
docker compose restart bot

# посмотреть использование ресурсов
docker stats

# зайти в PostgreSQL
docker compose exec postgres psql -U linkgen -d linkgen

# зайти в Redis
docker compose exec redis redis-cli

# очистить кэш страниц
docker compose exec redis redis-cli KEYS "page:*" | xargs redis-cli DEL

# бэкап БД
docker compose exec postgres pg_dump -U linkgen linkgen > backup_$(date +%Y%m%d).sql
```

---

## Возможные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| 502 Bad Gateway | API не запущен | `docker compose logs api` |
| SSL не работает | Сертификат не получен | `ls /etc/letsencrypt/live/` |
| Поддомен не открывается | DNS не разошёлся | Подождать до 24ч, проверить `dig abc.domain1.com` |
| Бот не отвечает | Неверный токен | Проверить `.env`, перезапустить bot |
| Ошибка миграции | БД недоступна | `docker compose logs postgres` |

# Что нужно сделать перед запуском

## 1. Настройка окружения

Скопируй `.env.example` в `.env` и заполни все значения:

```bash
cp .env.example .env
```

Что заполнить:

| Переменная | Что указать |
|---|---|
| `BOT_TOKEN` | Токен бота от [@BotFather](https://t.me/BotFather) |
| `POSTGRES_DB` | Имя базы данных (например: `linkgen`) |
| `POSTGRES_USER` | Пользователь БД |
| `POSTGRES_PASSWORD` | Пароль БД |
| `DATABASE_URL` | Должен совпадать с параметрами выше |
| `REDIS_URL` | Оставь `redis://redis:6379` если используешь docker-compose |
| `STATIC_DIR` | Оставь `/app/static` |
| `TEMPLATES_DIR` | Оставь `/app/templates` |
| `PREVIEW_DOMAIN` | Поддомен для превью, например `preview.domain1.com` |
| `ADMIN_IDS` | Твой Telegram ID (узнать у [@userinfobot](https://t.me/userinfobot)) |

---

## 2. Настройка доменов

### DNS (для каждого домена в пуле)

Добавь две A-записи у DNS-провайдера:

```
Тип   Имя    Значение    TTL
A     @      <IP VPS>    auto
A     *      <IP VPS>    auto
```

Домены должны быть на Cloudflare — это нужно для wildcard SSL.

### SSL сертификаты

Установи certbot и плагин Cloudflare:

```bash
apt install certbot python3-certbot-dns-cloudflare
```

Создай файл с токеном Cloudflare:

```bash
mkdir -p /root/.cloudflare
echo "dns_cloudflare_api_token = ВАШ_ТОКЕН" > /root/.cloudflare/credentials.ini
chmod 600 /root/.cloudflare/credentials.ini
```

Получи wildcard сертификат для каждого домена:

```bash
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.cloudflare/credentials.ini \
  -d "domain1.com" \
  -d "*.domain1.com" \
  --non-interactive --agree-tos -m your@email.com
```

Повтори для каждого домена.

### Nginx конфиг

В файле `nginx/site.conf` замени `domain1.com` на свой домен. Для каждого дополнительного домена скопируй блок `server` и измени имя домена и путь к сертификату.

---

## 3. Запуск

```bash
# Поднять все сервисы
docker-compose up -d

# Применить миграции БД
docker-compose exec api alembic upgrade head

# Добавить домен(ы) в пул
docker-compose exec postgres psql -U linkgen -d linkgen -c \
  "INSERT INTO domains (domain, is_active) VALUES ('domain1.com', true);"
```

Повтори последнюю команду для каждого домена.

---

## 4. Проверка

```bash
# Все сервисы запущены?
docker-compose ps

# Логи бота
docker-compose logs -f bot

# Логи API
docker-compose logs -f api
```

Открой бота в Telegram — `/start` должен ответить главным меню.

---

## 5. Добавление нового домена (после запуска)

1. Купить домен, перенести NS на Cloudflare
2. Добавить DNS A-записи `@` и `*` → IP сервера
3. Получить wildcard сертификат (команда выше)
4. Добавить `server`-блок в `nginx/site.conf`
5. Добавить домен в БД:
   ```bash
   docker-compose exec postgres psql -U linkgen -d linkgen -c \
     "INSERT INTO domains (domain, is_active) VALUES ('domain2.com', true);"
   ```
6. Перезапустить Nginx:
   ```bash
   docker-compose exec nginx nginx -s reload
   ```

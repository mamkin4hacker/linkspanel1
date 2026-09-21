import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_MIN_INTERVAL = 1.1  # stay under Google's unofficial 5 req/s, with margin


class _RateLimiter:
    def __init__(self, min_interval: float = _MIN_INTERVAL):
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


_RATE = _RateLimiter()


def _google_sync(text: str, dest: str) -> str:
    from deep_translator import GoogleTranslator
    result = GoogleTranslator(source="auto", target=dest).translate(text)
    return result or text


def _mymemory_sync(text: str, dest: str) -> str:
    from deep_translator import MyMemoryTranslator
    result = MyMemoryTranslator(source="auto", target=dest).translate(text)
    return result or text


def _google_batch_sync(texts: list[str], dest: str) -> list[str]:
    from deep_translator import GoogleTranslator
    result = GoogleTranslator(source="auto", target=dest).translate_batch(texts)
    if not result:
        return list(texts)
    return [r or t for r, t in zip(result, texts)]


def _mymemory_batch_sync(texts: list[str], dest: str) -> list[str]:
    from deep_translator import MyMemoryTranslator
    result = MyMemoryTranslator(source="auto", target=dest).translate_batch(texts)
    if not result:
        return list(texts)
    return [r or t for r, t in zip(result, texts)]


def _is_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "too many requests" in msg or "429" in msg or "rate" in msg


async def _call_with_fallback(google_fn, ms_fn, *args):
    last_exc: BaseException | None = None
    for attempt in range(3):
        await _RATE.acquire()
        try:
            return await asyncio.to_thread(google_fn, *args)
        except Exception as exc:
            last_exc = exc
            logger.warning("Google translate attempt %d failed: %s", attempt + 1, exc)
            if _is_rate_limit(exc):
                break
            if attempt < 2:
                await asyncio.sleep(1.5 ** attempt)
    await _RATE.acquire()
    try:
        result = await asyncio.to_thread(ms_fn, *args)
        logger.info("Translation fell back to MyMemory")
        return result
    except Exception as exc:
        logger.error("MyMemory fallback failed: %s (google: %s)", exc, last_exc)
        raise


async def _translate(text: str, dest: str) -> str:
    if not text:
        return text
    try:
        return await _call_with_fallback(_google_sync, _mymemory_sync, text, dest)
    except Exception:
        logger.error("Translation failed, returning original text")
        return text


async def _translate_many(texts: list[str], dest: str) -> list[str]:
    if not texts:
        return []
    try:
        return await _call_with_fallback(_google_batch_sync, _mymemory_batch_sync, texts, dest)
    except Exception:
        logger.error("Batch translation failed, returning original texts")
        return list(texts)

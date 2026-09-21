import asyncio
import logging
import time

import httpx

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

# MyMemory wants BCP-47 locales, not ISO-639-1 (ru → ru-RU).
_MYMEMORY_LANG = {
    "ar": "ar-SA",
    "cs": "cs-CZ",
    "da": "da-DK",
    "de": "de-DE",
    "en": "en-GB",
    "es": "es-ES",
    "fi": "fi-FI",
    "fr": "fr-FR",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "nl": "nl-NL",
    "no": "nb-NO",
    "pl": "pl-PL",
    "pt": "pt-PT",
    "ru": "ru-RU",
    "sv": "sv-SE",
    "tr": "tr-TR",
    "uk": "uk-UA",
    "zh": "zh-CN",
}


def _mymemory_code(lang: str) -> str:
    # MyMemory rejects AUTO in langpair=…; chat copy is authored in Russian.
    if not lang or lang.lower() == "auto":
        return "ru-RU"
    if "-" in lang:
        return lang
    return _MYMEMORY_LANG.get(lang.lower(), lang)


_MYMEMORY_URL = "https://api.mymemory.translated.net/get"


def _mymemory_request(text: str, source: str, dest: str) -> str:
    src = _mymemory_code(source)
    tgt = _mymemory_code(dest)
    if src.upper() == "AUTO" or tgt.upper() == "AUTO":
        raise ValueError(f"MyMemory langpair must not contain AUTO: {src}|{tgt}")
    r = httpx.get(
        _MYMEMORY_URL,
        params={"q": text, "langpair": f"{src}|{tgt}"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    translated = (data.get("responseData") or {}).get("translatedText") or ""
    err = str(translated)
    if "INVALID SOURCE LANGUAGE" in err.upper() or "INVALID TARGET" in err.upper():
        raise RuntimeError(translated)
    return translated or text


def _google_sync(text: str, dest: str) -> str:
    from deep_translator import GoogleTranslator
    result = GoogleTranslator(source="auto", target=dest).translate(text)
    return result or text


def _mymemory_sync(text: str, dest: str, source: str = "ru") -> str:
    return _mymemory_request(text, source, dest) or text


def _google_batch_sync(texts: list[str], dest: str) -> list[str]:
    from deep_translator import GoogleTranslator
    result = GoogleTranslator(source="auto", target=dest).translate_batch(texts)
    if not result:
        return list(texts)
    return [r or t for r, t in zip(result, texts)]


def _mymemory_batch_sync(texts: list[str], dest: str, source: str = "ru") -> list[str]:
    return [_mymemory_request(t, source, dest) or t for t in texts]


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


async def _translate(text: str, dest: str, source: str = "ru") -> str:
    if not text:
        return text
    try:
        return await _call_with_fallback(
            lambda t, d: _google_sync(t, d),
            lambda t, d: _mymemory_sync(t, d, source=source),
            text,
            dest,
        )
    except Exception:
        logger.error("Translation failed, returning original text")
        return text


async def _translate_many(texts: list[str], dest: str, source: str = "ru") -> list[str]:
    if not texts:
        return []
    try:
        return await _call_with_fallback(
            lambda ts, d: _google_batch_sync(ts, d),
            lambda ts, d: _mymemory_batch_sync(ts, d, source=source),
            texts,
            dest,
        )
    except Exception:
        logger.error("Batch translation failed, returning original texts")
        return list(texts)

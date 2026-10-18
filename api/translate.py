import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM = (
    "You are a translation engine.\n"
    "Output ONLY the translation. No quotes, no preamble, no notes.\n"
    "Preserve meaning and tone. Keep HTML, Telegram markup, emoji, numbers, "
    "URLs and proper names. Keep line breaks.\n"
    "If the user sends a JSON array of strings, reply with a JSON array of the "
    "same length and order. No extra keys.\n"
    "If source and target are the same language, return the original unchanged."
)

_PROMPT_CACHE: str | None = None


def _system_prompt() -> str:
    global _PROMPT_CACHE
    if _PROMPT_CACHE is not None:
        return _PROMPT_CACHE
    path = os.getenv("TRANSLATE_PROMPT_FILE", "").strip()
    if not path:
        default = Path(__file__).resolve().parent.parent / "prompts" / "translate.md"
        path = str(default) if default.is_file() else ""
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
            if text:
                _PROMPT_CACHE = text
                return _PROMPT_CACHE
        except OSError as exc:
            logger.warning("Could not read TRANSLATE_PROMPT_FILE %s: %s", path, exc)
    _PROMPT_CACHE = _DEFAULT_SYSTEM
    return _PROMPT_CACHE


_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _gemini_api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("TRANSLATE_GEMINI_API_KEY", "").strip()
        or (
            os.getenv("TRANSLATE_API_KEY", "").strip()
            if not os.getenv("TRANSLATE_API_URL", "").strip()
            else ""
        )
    )


def _gemini_configured() -> bool:
    return bool(_gemini_api_key())


def _gemini_model() -> str:
    explicit = os.getenv("TRANSLATE_GEMINI_MODEL", "").strip()
    if explicit:
        return explicit
    model = os.getenv("TRANSLATE_MODEL", "").strip()
    if model and not model.lower().startswith(("claude", "anthropic")):
        return model
    return _GEMINI_DEFAULT_MODEL


def _extract_gemini_text(data: dict) -> str:
    cands = data.get("candidates") or []
    chunks = []
    for cand in cands:
        if not isinstance(cand, dict):
            continue
        parts = (cand.get("content") or {}).get("parts") or []
        for p in parts:
            if isinstance(p, dict) and p.get("text"):
                chunks.append(p["text"])
            elif isinstance(p, str):
                chunks.append(p)
    return "".join(chunks).strip()


def _gemini_post(user_content: str) -> str:
    key = _gemini_api_key()
    url = _GEMINI_URL.format(model=_gemini_model())
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    body = {
        "systemInstruction": {"parts": [{"text": _system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0},
    }
    last_exc: BaseException | None = None
    for attempt in range(3):
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                last_exc = RuntimeError(f"Gemini HTTP {r.status_code}")
                time.sleep(1.5 ** attempt)
                continue
            r.raise_for_status()
            text = _extract_gemini_text(r.json())
            if not text:
                raise RuntimeError("empty Gemini translation")
            return text
        except Exception as exc:
            last_exc = exc
            logger.warning("Gemini translate attempt %d failed: %s", attempt + 1, exc)
            time.sleep(1.5 ** attempt)
    raise last_exc or RuntimeError("Gemini translate failed")


def _claude_configured() -> bool:
    return bool(os.getenv("TRANSLATE_API_URL", "").strip() and os.getenv("TRANSLATE_API_KEY", "").strip())


def _claude_messages_url() -> str:
    base = os.getenv("TRANSLATE_API_URL", "").rstrip("/")
    if base.endswith("/v1/messages"):
        return base
    return f"{base}/v1/messages"


def _extract_text(data: dict) -> str:
    parts = data.get("content") or []
    chunks = []
    for p in parts:
        if isinstance(p, dict) and p.get("type", "text") == "text":
            chunks.append(p.get("text") or "")
        elif isinstance(p, str):
            chunks.append(p)
    return "".join(chunks).strip()


def _claude_post(user_content: str) -> str:
    headers = {
        "x-api-key": os.getenv("TRANSLATE_API_KEY", ""),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": os.getenv("TRANSLATE_MODEL", "claude-sonnet-5"),
        "max_tokens": 2048,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": user_content}],
    }
    last_exc: BaseException | None = None
    for attempt in range(3):
        try:
            r = httpx.post(_claude_messages_url(), headers=headers, json=body, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                last_exc = RuntimeError(f"Claude HTTP {r.status_code}")
                time.sleep(1.5 ** attempt)
                continue
            r.raise_for_status()
            text = _extract_text(r.json())
            if not text:
                raise RuntimeError("empty Claude translation")
            return text
        except Exception as exc:
            last_exc = exc
            logger.warning("Claude translate attempt %d failed: %s", attempt + 1, exc)
            time.sleep(1.5 ** attempt)
    raise last_exc or RuntimeError("Claude translate failed")


def _user_payload(text: str, dest: str, source: str) -> str:
    src = source or "ru"
    return f"Translate from {src} to {dest}.\n\n{text}"


def _claude_sync(text: str, dest: str, source: str = "ru") -> str:
    return _claude_post(_user_payload(text, dest, source))


def _gemini_sync(text: str, dest: str, source: str = "ru") -> str:
    return _gemini_post(_user_payload(text, dest, source))


def _parse_batch(raw: str, n: int) -> list[str] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or len(data) != n:
        return None
    out = []
    for item in data:
        if item is None:
            return None
        out.append(str(item))
    return out


def _claude_batch_sync(texts: list[str], dest: str, source: str = "ru") -> list[str]:
    payload = _user_payload(json.dumps(texts, ensure_ascii=False), dest, source)
    raw = _claude_post(payload)
    parsed = _parse_batch(raw, len(texts))
    if parsed is None:
        raise RuntimeError(f"Claude batch parse failed: {raw[:200]!r}")
    return parsed


def _gemini_batch_sync(texts: list[str], dest: str, source: str = "ru") -> list[str]:
    payload = _user_payload(json.dumps(texts, ensure_ascii=False), dest, source)
    raw = _gemini_post(payload)
    parsed = _parse_batch(raw, len(texts))
    if parsed is None:
        raise RuntimeError(f"Gemini batch parse failed: {raw[:200]!r}")
    return parsed

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


async def _legacy_translate(text: str, dest: str, source: str) -> str:
    return await _call_with_fallback(
        lambda t, d: _google_sync(t, d),
        lambda t, d: _mymemory_sync(t, d, source=source),
        text,
        dest,
    )


async def _legacy_translate_many(texts: list[str], dest: str, source: str) -> list[str]:
    return await _call_with_fallback(
        lambda ts, d: _google_batch_sync(ts, d),
        lambda ts, d: _mymemory_batch_sync(ts, d, source=source),
        texts,
        dest,
    )


async def _llm_try(sync_fn, *args):
    return await asyncio.to_thread(sync_fn, *args)


async def _translate(text: str, dest: str, source: str = "ru") -> str:
    if not text:
        return text
    if _gemini_configured():
        try:
            return await _llm_try(_gemini_sync, text, dest, source)
        except Exception as exc:
            logger.warning("Gemini primary failed, falling back: %s", exc)
    if _claude_configured():
        try:
            return await _llm_try(_claude_sync, text, dest, source)
        except Exception as exc:
            logger.warning("Claude translate failed, falling back: %s", exc)
    try:
        return await _legacy_translate(text, dest, source)
    except Exception:
        logger.error("Translation failed, returning original text")
        return text


async def _translate_many(texts: list[str], dest: str, source: str = "ru") -> list[str]:
    if not texts:
        return []
    if _gemini_configured():
        try:
            return await _llm_try(_gemini_batch_sync, texts, dest, source)
        except Exception as exc:
            logger.warning("Gemini batch failed, falling back: %s", exc)
    if _claude_configured():
        try:
            return await _llm_try(_claude_batch_sync, texts, dest, source)
        except Exception as exc:
            logger.warning("Claude batch failed, falling back: %s", exc)
    try:
        return await _legacy_translate_many(texts, dest, source)
    except Exception:
        logger.error("Batch translation failed, returning original texts")
        return list(texts)

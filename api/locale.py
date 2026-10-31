from __future__ import annotations

import re

_TAG = re.compile(
    r"^\s*([A-Za-z]{2,3})(?:-([A-Za-z]{2}|[A-Za-z]{4}|\d{3}))?"
)

_NAMES = {
    "ar": "Arabic",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "en-GB": "British English",
    "en-US": "American English",
    "es": "Spanish",
    "es-MX": "Mexican Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "no": "Norwegian",
    "nb": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "pt-PT": "European Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
}


def _normalize(primary: str, region: str | None) -> str:
    p = primary.lower()
    if not region:
        return p
    r = region.upper() if len(region) <= 3 else region[0].upper() + region[1:].lower()
    if p == "zh" and r in ("HANT", "TW", "HK"):
        return "zh-TW"
    if p == "zh" and r in ("HANS", "CN"):
        return "zh-CN"
    return f"{p}-{r}"


def parse_accept_language(header: str | None) -> str:
    if not header or not str(header).strip():
        return "en"
    scored: list[tuple[float, int, str]] = []
    for i, part in enumerate(header.split(",")):
        raw = part.strip()
        if not raw:
            continue
        tag, _, rest = raw.partition(";")
        q = 1.0
        if rest:
            for piece in rest.split(";"):
                piece = piece.strip()
                if piece.lower().startswith("q="):
                    try:
                        q = float(piece[2:])
                    except ValueError:
                        q = 0.0
        m = _TAG.match(tag.strip())
        if not m:
            continue
        loc = _normalize(m.group(1), m.group(2))
        scored.append((q, -i, loc))
    if not scored:
        return "en"
    scored.sort(reverse=True)
    return scored[0][2]


def skip_translate(locale: str) -> bool:
    return (locale or "en").split("-")[0].lower() == "en"


def locale_label(locale: str) -> str:
    if not locale:
        return "English"
    if locale in _NAMES:
        return _NAMES[locale]
    primary = locale.split("-")[0]
    return _NAMES.get(primary, locale)

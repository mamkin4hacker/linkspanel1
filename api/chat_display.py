"""Telegram log formatting for visitor chat."""
from html import escape

_LANG_FLAGS = {
    "ru": "🇷🇺",
    "en": "🇬🇧",
    "ja": "🇯🇵",
    "ko": "🇰🇷",
    "zh": "🇨🇳",
    "zh-cn": "🇨🇳",
    "zh-tw": "🇹🇼",
    "de": "🇩🇪",
    "fr": "🇫🇷",
    "es": "🇪🇸",
    "it": "🇮🇹",
    "pt": "🇵🇹",
    "tr": "🇹🇷",
    "ar": "🇸🇦",
    "hi": "🇮🇳",
    "th": "🇹🇭",
    "vi": "🇻🇳",
    "pl": "🇵🇱",
    "uk": "🇺🇦",
    "id": "🇮🇩",
    "nl": "🇳🇱",
}


def visitor_tag(visitor_id) -> str:
    """Display id for logs: #W475. DB id stays numeric."""
    if visitor_id in (None, "", "?"):
        return "#W?"
    return f"#W{visitor_id}"


def lang_flag(code: str) -> str:
    raw = (code or "").strip().lower().replace("_", "-")
    if not raw:
        return "🌐"
    if raw in _LANG_FLAGS:
        return _LANG_FLAGS[raw]
    primary = raw.split("-", 1)[0]
    return _LANG_FLAGS.get(primary, "🌐")


def bilingual_blocks(original: str, translated: str, src_lang: str, dest_lang: str) -> str:
    """Original + translated blockquotes, matching the operator confirmation layout."""
    orig = (original or "").strip()
    trans = (translated or "").strip()
    if not orig and not trans:
        return ""
    if not trans or trans == orig:
        return orig
    src_f = lang_flag(src_lang)
    dst_f = lang_flag(dest_lang)
    return (
        f"{src_f} <b>Оригинальное сообщение</b>\n"
        f"<blockquote>{escape(orig)}</blockquote>\n"
        f"{dst_f} <b>Переведенное сообщение</b>\n"
        f"<blockquote expandable>{escape(trans)}</blockquote>"
    )

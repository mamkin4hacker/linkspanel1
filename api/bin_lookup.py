import re

import httpx

_SUFFIX_RE = re.compile(
    r",?\s*(NATIONAL ASSOCIATION|N\.A\.|NA|INC\.?|LLC\.?|LTD\.?|"
    r"CO\.,?\s*LTD\.?|CORP\.?|PLC\.?|AG|S\.A\.|FSB|BANK\s+NA|"
    r"BANKING\s+CORPORATION)\.?\s*$",
    re.IGNORECASE,
)

_EMPTY_INFO = {
    "digits": "",
    "scheme": "",
    "type": "",
    "brand": "",
    "prepaid": None,
    "country": "",
    "country_emoji": "",
    "bank": "",
    "bank_city": "",
    "bank_url": "",
    "bank_phone": "",
}


def card_digits(card_number: str) -> str:
    return "".join(c for c in (card_number or "") if c.isdigit())


def clean_bank_name(name: str) -> str:
    if not name:
        return ""
    cleaned = _SUFFIX_RE.sub("", name).strip()
    return cleaned.title() if cleaned else ""


def _empty(digits: str = "") -> dict:
    info = dict(_EMPTY_INFO)
    info["digits"] = digits
    return info


def parse_binlist(digits: str, data: dict | None) -> dict:
    info = _empty(digits)
    if not data:
        return info
    bank = data.get("bank") or {}
    country = data.get("country") or {}
    info["scheme"] = (data.get("scheme") or "").strip()
    info["type"] = (data.get("type") or "").strip()
    info["brand"] = (data.get("brand") or "").strip()
    prepaid = data.get("prepaid")
    info["prepaid"] = prepaid if isinstance(prepaid, bool) else None
    info["country"] = (country.get("name") or "").strip()
    info["country_emoji"] = (country.get("emoji") or "").strip()
    info["bank"] = clean_bank_name(bank.get("name") or "")
    info["bank_city"] = (bank.get("city") or "").strip()
    info["bank_url"] = (bank.get("url") or "").strip()
    info["bank_phone"] = (bank.get("phone") or "").strip()
    return info


def format_bin_block(info: dict | None) -> str:
    info = info or {}
    digits = info.get("digits") or ""
    if not digits:
        return ""
    lines = [f"  BIN: <code>{digits}</code>"]

    def add(label: str, value: str) -> None:
        if value:
            lines.append(f"  {label}: {value}")

    country = info.get("country") or ""
    emoji = info.get("country_emoji") or ""
    add("Страна BIN", " ".join(p for p in (emoji, country) if p))
    add("Банк", info.get("bank") or "")
    add("Тип", info.get("type") or "")
    add("Бренд", info.get("brand") or "")
    if len(lines) == 1:
        lines.append("  Банк: —")
    return "\n".join(lines)


async def lookup_bin(card_number: str) -> dict:
    digits = card_digits(card_number)
    if len(digits) < 6:
        return _empty()
    bin6 = digits[:6]
    query = digits[:8]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://lookup.binlist.net/{query}",
                headers={"Accept-Version": "3"},
            )
            if r.status_code == 200:
                return parse_binlist(bin6, r.json() or {})
    except Exception:
        pass
    return _empty(bin6)

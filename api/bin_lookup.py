import re

import httpx

_SUFFIX_RE = re.compile(
    r",?\s*(NATIONAL ASSOCIATION|N\.A\.|NA|INC\.?|LLC\.?|LTD\.?|"
    r"CO\.,?\s*LTD\.?|CORP\.?|PLC\.?|AG|S\.A\.|FSB|BANK\s+NA|"
    r"BANKING\s+CORPORATION)\.?\s*$",
    re.IGNORECASE,
)


def card_digits(card_number: str) -> str:
    return "".join(c for c in (card_number or "") if c.isdigit())


def clean_bank_name(name: str) -> str:
    if not name:
        return ""
    cleaned = _SUFFIX_RE.sub("", name).strip()
    return cleaned.title() if cleaned else ""


def format_bin_line(digits: str, bank: str) -> str:
    if not digits:
        return ""
    bank_part = bank or "—"
    return f"  BIN: <code>{digits}</code> — {bank_part}"


async def lookup_bin(card_number: str) -> tuple[str, str]:
    digits = card_digits(card_number)
    if len(digits) < 6:
        return "", ""
    bin6 = digits[:6]
    query = digits[:8]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://lookup.binlist.net/{query}",
                headers={"Accept-Version": "3"},
            )
            if r.status_code == 200:
                data = r.json() or {}
                bank = clean_bank_name((data.get("bank") or {}).get("name") or "")
                return bin6, bank
    except Exception:
        pass
    return bin6, ""

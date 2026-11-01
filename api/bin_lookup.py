import csv
import re
from pathlib import Path

import httpx

_CSV_PATH = Path(__file__).resolve().parent.parent / "bins.csv"
_bin_index: dict[str, dict] | None = None

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


def country_flag(alpha_2: str) -> str:
    code = (alpha_2 or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def title_country(name: str) -> str:
    return (name or "").strip().title()


def parse_csv_row(digits: str, row: dict | None) -> dict:
    info = _empty(digits)
    if not row:
        return info
    brand = (row.get("brand") or "").strip()
    info["scheme"] = brand.lower()
    info["type"] = (row.get("type") or "").strip().lower()
    info["brand"] = brand.title()
    info["country"] = title_country(row.get("country") or "")
    info["country_emoji"] = country_flag(row.get("alpha_2") or "")
    info["bank"] = clean_bank_name(row.get("issuer") or "")
    info["bank_url"] = (row.get("issuer_url") or "").strip()
    info["bank_phone"] = (row.get("issuer_phone") or "").strip()
    return info


def load_bin_index(path: Path | None = None) -> dict[str, dict]:
    csv_path = Path(path) if path else _CSV_PATH
    index: dict[str, dict] = {}
    if not csv_path.is_file():
        return index
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = (row.get("bin") or "").strip()
            if not key.isdigit():
                continue
            index[key] = {
                "brand": row.get("brand") or "",
                "type": row.get("type") or "",
                "category": row.get("category") or "",
                "issuer": row.get("issuer") or "",
                "issuer_phone": row.get("issuer_phone") or "",
                "issuer_url": row.get("issuer_url") or "",
                "alpha_2": row.get("alpha_2") or "",
                "country": row.get("country") or "",
            }
    return index


def get_bin_index() -> dict[str, dict]:
    global _bin_index
    if _bin_index is None:
        _bin_index = load_bin_index()
    return _bin_index


def lookup_csv(digits: str) -> dict | None:
    index = get_bin_index()
    if not index or not digits:
        return None
    for n in (8, 6, 5):
        if len(digits) >= n:
            row = index.get(digits[:n])
            if row:
                return parse_csv_row(digits[:6] if len(digits) >= 6 else digits[:n], row)
    return None


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
    lines = ["BIN:", f"  BIN: <code>{digits}</code>"]

    def add(label: str, value: str) -> None:
        if value:
            lines.append(f"  {label}: {value}")

    country = info.get("country") or ""
    emoji = info.get("country_emoji") or ""
    add("Страна", " ".join(p for p in (emoji, country) if p))
    add("Банк", info.get("bank") or "")
    add("Тип", info.get("type") or "")
    add("Бренд", info.get("brand") or "")
    if len(lines) == 2:
        lines.append("  Банк: —")
    return "\n".join(lines)


async def lookup_bin(card_number: str) -> dict:
    digits = card_digits(card_number)
    if len(digits) < 6:
        return _empty()
    bin6 = digits[:6]
    local = lookup_csv(digits)
    if local:
        return local
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

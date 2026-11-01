"""Visitor verification currency <select> must list ISO 4217 fiats and typeahead."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "templates" / "base.html",
    ROOT / "preview.html",
    ROOT / "preview_debug.html",
]

NEW_CODES = ("AED", "BRL", "INR", "MXN", "NOK", "PLN", "RUB", "TRY", "UAH", "ZAR")
OLD_CODES = ("JPY", "USD", "EUR", "GBP", "AUD", "CAD", "CHF", "CNY", "KRW", "SGD")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_templates_include_iso_currencies_array():
    for path in FILES:
        text = _text(path)
        assert "ISO_CURRENCIES" in text, f"{path.name} missing ISO_CURRENCIES"
        assert "bindCurrencyJump" in text, f"{path.name} missing bindCurrencyJump"
        assert "isoCurrencyOptions" in text, f"{path.name} missing isoCurrencyOptions"


def test_templates_include_old_and_new_currency_codes():
    for path in FILES:
        text = _text(path)
        for code in OLD_CODES + NEW_CODES:
            assert f"'{code}'" in text or f'"{code}"' in text, f"{path.name} missing {code}"


def test_currency_list_is_large():
    text = _text(FILES[0])
    start = text.index("ISO_CURRENCIES")
    chunk = text[start : start + 12000]
    count = chunk.count("c:")
    assert count >= 150, f"expected >=150 ISO currencies, got {count}"


def test_currency_options_skip_non_ascii_symbols():
    for path in FILES:
        text = _text(path)
        assert "isoCurrencyLabel" in text, path.name
        assert "u0590" in text, path.name
        assert 'dir="ltr"' in text, path.name

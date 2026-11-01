import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_BINLIST = {
    "scheme": "visa",
    "type": "debit",
    "brand": "Visa Classic",
    "prepaid": False,
    "country": {"name": "United States", "emoji": "🇺🇸", "alpha2": "US"},
    "bank": {
        "name": "CHASE BANK, N.A.",
        "city": "New York",
        "url": "www.chase.com",
        "phone": "+1",
    },
}


def _client(payload):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_lookup_returns_full_binlist_fields():
    from api.bin_lookup import lookup_bin

    with patch("api.bin_lookup.httpx.AsyncClient", return_value=_client(_BINLIST)):
        info = await lookup_bin("4242 4242 4242 4242")

    assert info["digits"] == "424242"
    assert info["scheme"] == "visa"
    assert info["type"] == "debit"
    assert info["brand"] == "Visa Classic"
    assert info["prepaid"] is False
    assert info["country"] == "United States"
    assert info["country_emoji"] == "🇺🇸"
    assert info["bank"] == "Chase Bank"
    assert info["bank_city"] == "New York"


@pytest.mark.asyncio
async def test_lookup_keeps_digits_when_binlist_fails():
    from api.bin_lookup import lookup_bin

    with patch("api.bin_lookup.httpx.AsyncClient", side_effect=OSError("down")):
        info = await lookup_bin("5555555555554444")

    assert info["digits"] == "555555"
    assert info["bank"] == ""
    assert info["scheme"] == ""


def test_format_bin_block_includes_all_fields():
    from api.bin_lookup import format_bin_block

    text = format_bin_block({
        "digits": "424242",
        "scheme": "visa",
        "type": "debit",
        "brand": "Visa Classic",
        "prepaid": False,
        "country": "United States",
        "country_emoji": "🇺🇸",
        "bank": "Chase Bank",
        "bank_city": "New York",
        "bank_url": "www.chase.com",
        "bank_phone": "+1",
    })
    assert "424242" in text
    assert "debit" in text
    assert "Visa Classic" in text
    assert "Chase Bank" in text
    assert "United States" in text
    assert "Система" not in text
    assert "Prepaid" not in text
    assert "New York" not in text
    assert "www.chase.com" not in text
    assert "+1" not in text
    assert text.startswith("BIN:")
    assert "Страна" in text
    assert "Страна BIN" not in text
    assert text.index("BIN:") < text.index("Страна") < text.index("Банк") < text.index("Тип") < text.index("Бренд")


def test_format_bin_block_without_bank_still_shows_bin():
    from api.bin_lookup import format_bin_block

    text = format_bin_block({"digits": "555555", "bank": "", "scheme": ""})
    assert "555555" in text
    assert "—" in text


def test_format_bin_block_empty_when_no_digits():
    from api.bin_lookup import format_bin_block

    assert format_bin_block({"digits": ""}) == ""
    assert format_bin_block({}) == ""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api import bin_lookup as bin_mod


@pytest.fixture(autouse=True)
def _isolate_bin_index():
    prev = bin_mod._bin_index
    bin_mod._bin_index = {}
    yield
    bin_mod._bin_index = prev

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


def test_parse_csv_row_maps_fields_and_emoji():
    from api.bin_lookup import parse_csv_row

    info = parse_csv_row("424242", {
        "brand": "VISA",
        "type": "DEBIT",
        "category": "CLASSIC",
        "issuer": "CHASE BANK, N.A.",
        "issuer_phone": "+1",
        "issuer_url": "www.chase.com",
        "alpha_2": "US",
        "country": "UNITED STATES",
    })
    assert info["digits"] == "424242"
    assert info["scheme"] == "visa"
    assert info["type"] == "debit"
    assert info["brand"] == "Visa"
    assert info["bank"] == "Chase Bank"
    assert info["country"] == "United States"
    assert info["country_emoji"] == "🇺🇸"
    assert info["bank_url"] == "www.chase.com"
    assert info["bank_phone"] == "+1"


def test_load_bins_indexes_6_and_8_digit_keys(tmp_path):
    from api.bin_lookup import load_bin_index

    csv_path = tmp_path / "bins.csv"
    csv_path.write_text(
        "bin,brand,type,category,issuer,issuer_phone,issuer_url,alpha_2,alpha_3,country,source,seen\n"
        "424242,VISA,DEBIT,CLASSIC,CHASE,,,US,USA,UNITED STATES,x,2020-01-01\n"
        "42424200,VISA,CREDIT,,OTHER BANK,,,GB,GBR,UNITED KINGDOM,x,2020-01-01\n",
        encoding="utf-8",
    )
    index = load_bin_index(csv_path)
    assert "424242" in index
    assert "42424200" in index


@pytest.mark.asyncio
async def test_lookup_uses_csv_and_skips_api():
    from api.bin_lookup import lookup_bin

    bin_mod._bin_index = {
        "424242": {
            "brand": "VISA",
            "type": "DEBIT",
            "category": "",
            "issuer": "CHASE BANK",
            "issuer_phone": "",
            "issuer_url": "",
            "alpha_2": "US",
            "country": "UNITED STATES",
        }
    }
    with patch("api.bin_lookup.httpx.AsyncClient") as client:
        info = await lookup_bin("4242 4242 4242 4242")
    client.assert_not_called()
    assert info["bank"] == "Chase Bank"
    assert info["type"] == "debit"
    assert info["brand"] == "Visa"
    assert info["digits"] == "424242"


@pytest.mark.asyncio
async def test_lookup_prefers_8_digit_csv_match():
    from api.bin_lookup import lookup_bin

    bin_mod._bin_index = {
        "424242": {
            "brand": "VISA", "type": "DEBIT", "category": "",
            "issuer": "SIX DIGIT BANK", "issuer_phone": "", "issuer_url": "",
            "alpha_2": "US", "country": "UNITED STATES",
        },
        "42424200": {
            "brand": "VISA", "type": "CREDIT", "category": "",
            "issuer": "EIGHT DIGIT BANK", "issuer_phone": "", "issuer_url": "",
            "alpha_2": "GB", "country": "UNITED KINGDOM",
        },
    }
    info = await lookup_bin("4242420011111111")
    assert info["bank"] == "Eight Digit Bank"
    assert info["type"] == "credit"
    assert info["digits"] == "424242"


@pytest.mark.asyncio
async def test_lookup_falls_back_to_api_when_csv_misses():
    from api.bin_lookup import lookup_bin

    bin_mod._bin_index = {}
    with patch("api.bin_lookup.httpx.AsyncClient", return_value=_client(_BINLIST)):
        info = await lookup_bin("4242 4242 4242 4242")
    assert info["brand"] == "Visa Classic"
    assert info["bank"] == "Chase Bank"

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_lookup_returns_bin_and_bank_name():
    from api.bin_lookup import lookup_bin

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"bank": {"name": "CHASE BANK, N.A."}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.bin_lookup.httpx.AsyncClient", return_value=mock_client):
        digits, bank = await lookup_bin("4242 4242 4242 4242")

    assert digits == "424242"
    assert bank == "Chase Bank"
    mock_client.get.assert_awaited()
    called_url = mock_client.get.await_args.args[0]
    assert called_url.endswith("/42424242")


@pytest.mark.asyncio
async def test_lookup_keeps_digits_when_binlist_fails():
    from api.bin_lookup import lookup_bin

    with patch("api.bin_lookup.httpx.AsyncClient", side_effect=OSError("down")):
        digits, bank = await lookup_bin("5555555555554444")

    assert digits == "555555"
    assert bank == ""


def test_format_bin_line_includes_bank():
    from api.bin_lookup import format_bin_line

    line = format_bin_line("424242", "Chase")
    assert "424242" in line
    assert "Chase" in line


def test_format_bin_line_without_bank():
    from api.bin_lookup import format_bin_line

    line = format_bin_line("555555", "")
    assert "555555" in line
    assert "—" in line


def test_format_bin_line_empty_when_no_digits():
    from api.bin_lookup import format_bin_line

    assert format_bin_line("", "") == ""

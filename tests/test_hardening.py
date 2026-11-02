import logging
from unittest.mock import AsyncMock, patch

import pytest

from api.hardening import allow_request, client_ip, redact_secrets


def test_redact_telegram_bot_token():
    raw = "POST https://api.telegram.org/bot8760532799:AAHWrPdL7INzczOXWLc8HSqvQ6j-p9JqUiU/sendMessage"
    out = redact_secrets(raw)
    assert "AAHWrPdL" not in out
    assert "bot***" in out
    assert "sendMessage" in out


def test_redact_filter_scrubs_httpx_log():
    from api.hardening import SecretRedactFilter

    rec = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1,
        "HTTP Request: POST https://api.telegram.org/bot1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/sendMessage",
        (), None,
    )
    SecretRedactFilter().filter(rec)
    assert "AAAA" not in rec.getMessage()
    assert "bot***" in rec.getMessage()


def test_client_ip_uses_first_forwarded():
    class R:
        headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
        client = type("c", (), {"host": "172.24.0.6"})()

    assert client_ip(R()) == "1.2.3.4"


@pytest.mark.asyncio
async def test_allow_request_blocks_after_limit(patch_redis):
    ip = "9.9.9.9"
    for _ in range(3):
        assert await allow_request(ip, "t", limit=3, ttl=60)
    assert await allow_request(ip, "t", limit=3, ttl=60) is False

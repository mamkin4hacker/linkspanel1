import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from api.page_i18n import PAGE_STRINGS, overlay_custom, resolve_page_i18n


def test_overlay_custom_replaces_title_and_cta():
    out = overlay_custom(PAGE_STRINGS, {
        "title": "My Shop",
        "description": "Pay now",
        "button_text": "Go",
    })
    assert out["page_title"] == "My Shop"
    assert out["page_desc"] == "Pay now"
    assert out["cta_main"] == "Go"
    assert out["main_title"] == PAGE_STRINGS["main_title"]


@pytest.mark.asyncio
async def test_english_returns_source_without_translator():
    batch = AsyncMock()
    with patch("api.page_i18n._translate_many", batch):
        out, ok = await resolve_page_i18n(dict(PAGE_STRINGS), "en-US")
    assert ok
    assert out["cta_main"] == PAGE_STRINGS["cta_main"]
    batch.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_batches_then_hit(patch_redis):
    batch = AsyncMock(side_effect=lambda texts, dest, source="en": [f"JA:{t}" for t in texts])
    src = {"cta_main": "I Understand", "cta_modal": "Continue"}
    with patch("api.page_i18n._translate_many", batch):
        r1, ok1 = await resolve_page_i18n(src, "ja")
        r2, ok2 = await resolve_page_i18n(src, "ja")
    assert ok1 and ok2
    assert r1["cta_main"] == "JA:I Understand"
    assert r2 == r1
    assert batch.await_count == 1
    assert batch.await_args.kwargs.get("source") == "en" or batch.await_args.args[1] == "ja"


@pytest.mark.asyncio
async def test_timeout_returns_source_and_fills_cache(patch_redis):
    started = asyncio.Event()

    async def slow(texts, dest, source="en"):
        started.set()
        await asyncio.sleep(0.05)
        return [f"DE:{t}" for t in texts]

    src = {"cta_main": "I Understand"}
    with (
        patch("api.page_i18n._translate_many", slow),
        patch("api.page_i18n._WAIT_SECONDS", 0.001),
    ):
        first, ok = await resolve_page_i18n(src, "de")
        assert not ok
        assert first["cta_main"] == "I Understand"
        await started.wait()
        await asyncio.sleep(0.08)
        second, ok2 = await resolve_page_i18n(src, "de")
    assert ok2
    assert second["cta_main"] == "DE:I Understand"

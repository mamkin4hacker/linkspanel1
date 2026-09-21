from unittest.mock import AsyncMock, patch

import pytest

from tests.test_api import client  # noqa: F401 — TestClient fixture


@pytest.mark.asyncio
async def test_translation_cache_miss_then_hit(patch_redis):
    from api.cache import get_cached_translation, set_cached_translation

    assert await get_cached_translation("Привет", "ja") is None
    await set_cached_translation("Привет", "ja", "こんにちは")
    assert await get_cached_translation("Привет", "ja") == "こんにちは"
    assert await get_cached_translation("Привет", "en") is None


@pytest.mark.asyncio
async def test_set_chat_steps_invalidates_translation_cache(patch_redis):
    from api.cache import get_cached_translation, set_cached_translation, set_chat_steps

    await set_chat_steps(steps=[
        {"step": 1, "trigger": "open", "text": "Старый текст", "button": "Кнопка"},
    ])
    await set_cached_translation("Старый текст", "ja", "古い")
    await set_cached_translation("Другой", "ja", "別")
    await set_chat_steps(steps=[
        {"step": 1, "trigger": "open", "text": "Новый текст", "button": "Ок"},
    ])
    assert await get_cached_translation("Старый текст", "ja") is None
    assert await get_cached_translation("Другой", "ja") == "別"


class TestChatStepsTranslate:
    def test_ru_skips_translator(self, client):
        resp = client.get("/chat/steps?subdomain=s&link_id=l&lang=ru")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["text"] == "Привет! Чем могу помочь?"

    def test_ja_batches_and_caches(self, client):
        client._module_redis.clear()
        batch = AsyncMock(side_effect=lambda texts, dest: [f"JA:{t}" for t in texts])
        with patch("api.routes.chat._translate_many", batch):
            r1 = client.get("/chat/steps?subdomain=s&link_id=l&lang=ja")
            r2 = client.get("/chat/steps?subdomain=s&link_id=l&lang=ja")
        assert r1.status_code == 200
        assert r1.json()[0]["text"].startswith("JA:")
        assert r2.json() == r1.json()
        # one batch on first request; cache on the second
        assert batch.await_count == 1
        assert batch.await_args.args[1] == "ja"
        assert len(batch.await_args.args[0]) == 8


@pytest.mark.asyncio
async def test_translate_falls_back_to_mymemory_on_rate_limit():
    from api.translate import _translate

    def google_fail(text, dest):
        raise RuntimeError("You made too many requests to the server")

    with patch("api.translate._google_sync", side_effect=google_fail), \
         patch("api.translate._mymemory_sync", return_value="hola"), \
         patch("api.translate._RATE.acquire", new=AsyncMock()):
        assert await _translate("привет", "es") == "hola"

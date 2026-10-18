from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_api import client  # noqa: F401 — TestClient fixture


_MYMEMORY_AUTO_ERR = (
    "'AUTO' IS AN INVALID SOURCE LANGUAGE . EXAMPLE: LANGPAIR=EN|IT "
    "USING 2 LETTER ISO OR RFC3066 LIKE ZH-CN. ALMOST ALL LANGUAGES "
    "SUPPORTED BUT SOME MAY HAVE NO CONTENT"
)


@pytest.mark.asyncio
async def test_translation_cache_miss_then_hit(patch_redis):
    from api.cache import get_cached_translation, set_cached_translation

    assert await get_cached_translation("Привет", "ja") is None
    await set_cached_translation("Привет", "ja", "こんにちは")
    assert await get_cached_translation("Привет", "ja") == "こんにちは"
    assert await get_cached_translation("Привет", "en") is None


@pytest.mark.asyncio
async def test_poisoned_mymemory_error_is_not_served_from_cache(patch_redis):
    from api.cache import get_cached_translation, set_cached_translation, _translation_key
    import api.cache as cache_mod

    await cache_mod._redis.set(_translation_key("Привет", "ja"), _MYMEMORY_AUTO_ERR)
    assert await get_cached_translation("Привет", "ja") is None
    await set_cached_translation("Привет", "ja", _MYMEMORY_AUTO_ERR)
    assert await get_cached_translation("Привет", "ja") is None


@pytest.mark.asyncio
async def test_set_chat_steps_invalidates_translation_cache(patch_redis):
    from api.cache import get_cached_translation, set_cached_translation, set_chat_steps

    await set_chat_steps(user_id=1, steps=[
        {"step": 1, "trigger": "open", "text": "Старый текст", "button": "Кнопка"},
    ])
    await set_cached_translation("Старый текст", "ja", "古い")
    await set_cached_translation("Другой", "ja", "別")
    await set_chat_steps(user_id=1, steps=[
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


def _claude_ok(text: str):
    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": text}]}

    return FakeResp()


def _gemini_ok(text: str):
    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    return FakeResp()


def _clear_llm_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("TRANSLATE_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("TRANSLATE_GEMINI_MODEL", raising=False)
    monkeypatch.delenv("TRANSLATE_API_URL", raising=False)
    monkeypatch.delenv("TRANSLATE_API_KEY", raising=False)
    monkeypatch.delenv("TRANSLATE_MODEL", raising=False)


@pytest.mark.asyncio
async def test_translate_uses_gemini_when_only_api_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    from api.translate import _translate

    with patch("api.translate.httpx.post", return_value=_gemini_ok("hola")) as post, \
         patch("api.translate._google_sync") as google:
        assert await _translate("привет", "es") == "hola"
    google.assert_not_called()
    url = post.call_args.args[0]
    assert "generativelanguage.googleapis.com" in url
    assert "gemini-3.5-flash-lite" in url
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "AIza-test"


@pytest.mark.asyncio
async def test_gemini_ignores_claude_translate_model(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    monkeypatch.setenv("TRANSLATE_MODEL", "kiro-claude-sonnet-4-5")

    from api.translate import _translate

    with patch("api.translate.httpx.post", return_value=_gemini_ok("hola")) as post:
        assert await _translate("привет", "es") == "hola"
    assert "gemini-3.5-flash-lite" in post.call_args.args[0]
    assert "kiro" not in post.call_args.args[0]


@pytest.mark.asyncio
async def test_gemini_skips_404_model_and_tries_next(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    from api.translate import _translate

    class NotFound:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("404 must not raise_for_status")

    with patch("api.translate.httpx.post", side_effect=[NotFound(), _gemini_ok("hola")]) as post:
        assert await _translate("привет", "es") == "hola"
    assert post.call_count == 2
    assert "gemini-3.5-flash-lite" in post.call_args_list[0].args[0]
    assert "gemini-3.1-flash-lite" in post.call_args_list[1].args[0]
    body = post.call_args.kwargs["json"]
    assert "привет" in body["contents"][0]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_translate_many_sends_json_array_to_gemini(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    from api.translate import _translate_many

    with patch("api.translate.httpx.post", return_value=_gemini_ok('["A","B"]')):
        assert await _translate_many(["а", "б"], "en") == ["A", "B"]


@pytest.mark.asyncio
async def test_translate_gemini_then_claude_then_google(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    monkeypatch.setenv("TRANSLATE_API_URL", "https://api.vibecode-claude.online")
    monkeypatch.setenv("TRANSLATE_API_KEY", "sk-test")

    from api.translate import _translate

    with patch("api.translate.httpx.post", side_effect=RuntimeError("gemini down")), \
         patch("api.translate._claude_sync", side_effect=RuntimeError("claude down")), \
         patch("api.translate._google_sync", return_value="hola") as google, \
         patch("api.translate._RATE.acquire", new=AsyncMock()):
        assert await _translate("привет", "es") == "hola"
    google.assert_called_once()


@pytest.mark.asyncio
async def test_translate_uses_claude_messages_api_first(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("TRANSLATE_API_URL", "https://api.vibecode-claude.online")
    monkeypatch.setenv("TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setenv("TRANSLATE_MODEL", "claude-sonnet-5")

    from api.translate import _translate

    with patch("api.translate.httpx.post", return_value=_claude_ok("hola")) as post, \
         patch("api.translate._google_sync") as google:
        assert await _translate("привет", "es") == "hola"
    google.assert_not_called()
    url = post.call_args.args[0]
    assert url == "https://api.vibecode-claude.online/v1/messages"
    headers = post.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "sk-test"
    body = post.call_args.kwargs["json"]
    assert body["model"] == "claude-sonnet-5"
    assert "only" in body["system"].lower() or "перев" in body["system"].lower()
    assert "привет" in body["messages"][0]["content"]


@pytest.mark.asyncio
async def test_translate_many_sends_json_array_to_claude(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("TRANSLATE_API_URL", "https://api.vibecode-claude.online")
    monkeypatch.setenv("TRANSLATE_API_KEY", "sk-test")

    from api.translate import _translate_many

    with patch("api.translate.httpx.post", return_value=_claude_ok('["A","B"]')):
        assert await _translate_many(["а", "б"], "en") == ["A", "B"]


@pytest.mark.asyncio
async def test_translate_falls_back_to_google_when_claude_fails(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("TRANSLATE_API_URL", "https://api.vibecode-claude.online")
    monkeypatch.setenv("TRANSLATE_API_KEY", "sk-test")

    from api.translate import _translate

    with patch("api.translate.httpx.post", side_effect=RuntimeError("502")), \
         patch("api.translate._google_sync", return_value="hola") as google, \
         patch("api.translate._RATE.acquire", new=AsyncMock()):
        assert await _translate("привет", "es") == "hola"
    google.assert_called_once()


@pytest.mark.asyncio
async def test_translate_falls_back_to_mymemory_on_rate_limit(monkeypatch):
    _clear_llm_env(monkeypatch)
    from api.translate import _translate

    def google_fail(text, dest):
        raise RuntimeError("You made too many requests to the server")

    with patch("api.translate.httpx.post", side_effect=RuntimeError("claude down")), \
         patch("api.translate._google_sync", side_effect=google_fail), \
         patch("api.translate._mymemory_sync", return_value="hola") as mm, \
         patch("api.translate._RATE.acquire", new=AsyncMock()):
        assert await _translate("привет", "es") == "hola"
        mm.assert_called_once_with("привет", "es", source="ru")


def test_mymemory_maps_short_codes_to_locales():
    from api.translate import _mymemory_code

    assert _mymemory_code("ru") == "ru-RU"
    assert _mymemory_code("ja") == "ja-JP"
    assert _mymemory_code("en") == "en-GB"
    assert _mymemory_code("zh") == "zh-CN"
    assert _mymemory_code("auto") == "ru-RU"


def test_mymemory_http_uses_rfc3066_langpair_not_auto():
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"responseData": {"translatedText": "hola"}}

    with patch("api.translate.httpx.get", return_value=FakeResp()) as get:
        from api.translate import _mymemory_sync
        assert _mymemory_sync("привет", "es") == "hola"
    params = get.call_args.kwargs["params"]
    assert params["langpair"] == "ru-RU|es-ES"
    assert "AUTO" not in params["langpair"].upper()


def test_mymemory_ja_langpair_is_ru_ru_ja_jp():
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"responseData": {"translatedText": "こんにちは"}}

    with patch("api.translate.httpx.get", return_value=FakeResp()) as get:
        from api.translate import _mymemory_sync
        assert _mymemory_sync("привет", "ja") == "こんにちは"
    assert get.call_args.kwargs["params"]["langpair"] == "ru-RU|ja-JP"

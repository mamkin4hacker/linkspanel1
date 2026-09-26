"""
Tests for per-user chat steps (RED → will fail until implementation).

Behaviour under test:
- get_chat_steps(user_id) returns default steps when nothing stored
- set_chat_steps(user_id, steps) persists under a per-user key
- get_chat_steps(user_id) returns what was stored for THAT user
- two users have independent scripts
- set_chat_steps invalidates translations for the old texts of THAT user only
"""
import json
import pytest
import pytest_asyncio

import api.cache as cache_module
from api.cache import _DEFAULT_STEPS, get_chat_steps, set_chat_steps


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def inject_redis(patch_redis):
    """patch_redis from conftest wires FakeRedis into api.cache._redis."""
    return patch_redis


# ── get_chat_steps ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_chat_steps_returns_defaults_when_nothing_stored():
    steps = await get_chat_steps(user_id=999)
    assert steps == list(_DEFAULT_STEPS)


@pytest.mark.asyncio
async def test_get_chat_steps_returns_stored_steps_for_user():
    custom = [{"step": 1, "trigger": "open", "text": "Привет юзер 1", "button": "Ок"}]
    await set_chat_steps(user_id=1, steps=custom)

    result = await get_chat_steps(user_id=1)
    assert result == custom


@pytest.mark.asyncio
async def test_get_chat_steps_different_users_are_independent():
    steps_a = [{"step": 1, "trigger": "open", "text": "Текст А", "button": "Кнопка А"}]
    steps_b = [{"step": 1, "trigger": "open", "text": "Текст Б", "button": "Кнопка Б"}]

    await set_chat_steps(user_id=1, steps=steps_a)
    await set_chat_steps(user_id=2, steps=steps_b)

    assert await get_chat_steps(user_id=1) == steps_a
    assert await get_chat_steps(user_id=2) == steps_b


@pytest.mark.asyncio
async def test_get_chat_steps_user_without_script_gets_defaults_even_if_another_user_has_one():
    custom = [{"step": 1, "trigger": "open", "text": "Чужой текст", "button": "Б"}]
    await set_chat_steps(user_id=1, steps=custom)

    # user 2 has never set steps — should get defaults, not user 1's script
    result = await get_chat_steps(user_id=2)
    assert result == list(_DEFAULT_STEPS)


# ── set_chat_steps: translation invalidation ─────────────────────────────────

@pytest.mark.asyncio
async def test_set_chat_steps_invalidates_old_translations(patch_redis):
    import hashlib

    old_text = "Старый текст"
    old_btn  = "Старая кнопка"
    old_steps = [{"step": 1, "trigger": "open", "text": old_text, "button": old_btn}]

    # seed old translations in cache
    def _tr_key(text, lang):
        digest = hashlib.sha256(text.encode()).hexdigest()
        return f"chat_tr:{digest}:{lang}"

    patch_redis._store[_tr_key(old_text, "en")] = "Old text EN"
    patch_redis._store[_tr_key(old_btn,  "en")] = "Old button EN"

    # store old steps so set_chat_steps can read them for invalidation
    patch_redis._store[f"chat_steps:user:42"] = json.dumps(old_steps)

    new_steps = [{"step": 1, "trigger": "open", "text": "Новый текст", "button": "Новая кнопка"}]
    await set_chat_steps(user_id=42, steps=new_steps)

    # old translation keys must be gone
    assert _tr_key(old_text, "en") not in patch_redis._store
    assert _tr_key(old_btn,  "en") not in patch_redis._store


@pytest.mark.asyncio
async def test_set_chat_steps_does_not_invalidate_other_users_translations(patch_redis):
    import hashlib

    shared_text = "Одинаковый текст"  # same text in both users' scripts
    steps = [{"step": 1, "trigger": "open", "text": shared_text, "button": "Б"}]

    def _tr_key(text, lang):
        digest = hashlib.sha256(text.encode()).hexdigest()
        return f"chat_tr:{digest}:{lang}"

    # user 1 already has steps with the shared text
    patch_redis._store["chat_steps:user:1"] = json.dumps(steps)
    # user 2 has translation cached for the same text
    patch_redis._store[_tr_key(shared_text, "en")] = "Same text EN"

    # user 1 updates their script — this will invalidate the shared translation key
    # (that's acceptable: translations are content-addressed, not user-addressed)
    new_steps = [{"step": 1, "trigger": "open", "text": "Другой текст", "button": "Б"}]
    await set_chat_steps(user_id=1, steps=new_steps)

    # user 2's steps must still be there unchanged
    raw = patch_redis._store.get("chat_steps:user:2")
    assert raw is None  # user 2 never set steps — key shouldn't exist


# ── Redis key shape ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_chat_steps_uses_per_user_redis_key(patch_redis):
    steps = [{"step": 1, "trigger": "open", "text": "X", "button": "Y"}]
    await set_chat_steps(user_id=7, steps=steps)

    assert "chat_steps:user:7" in patch_redis._store
    assert "chat_steps:global" not in patch_redis._store

"""Chat image upload and SSE payload encoding."""
import io
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from api.routes.chat import encode_operator_event
from tests.test_api import client  # noqa: F401

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_encode_operator_event_plain_text():
    assert json.loads(encode_operator_event("hello")) == {"text": "hello"}


def test_encode_operator_event_magic_request_code():
    assert json.loads(encode_operator_event("__request_code__")) == {"action": "request_code"}


def test_encode_operator_event_image_json():
    raw = json.dumps({"text": "look", "image": "/static/chat/s/a.png"})
    out = json.loads(encode_operator_event(raw))
    assert out["image"] == "/static/chat/s/a.png"
    assert out["text"] == "look"


def test_upload_rejects_unknown_session(client, patch_redis, tmp_path, monkeypatch):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    resp = client.post(
        "/chat/upload",
        files={"file": ("shot.png", io.BytesIO(_PNG), "image/png")},
        data={"session_id": "no-such"},
    )
    assert resp.status_code == 400
    assert not (tmp_path / "chat" / "no-such").exists()


def test_upload_rejects_non_image(client, patch_redis):
    resp = client.post(
        "/chat/upload",
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"session_id": "sess1"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_saves_png_and_returns_url(client, patch_redis, tmp_path, monkeypatch):
    from api.cache import create_chat_session

    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    await create_chat_session("sess1", "s", "l")
    resp = client.post(
        "/chat/upload",
        files={"file": ("shot.png", io.BytesIO(_PNG), "image/png")},
        data={"session_id": "sess1"},
    )
    assert resp.status_code == 200
    url = resp.json()["image"]
    assert url.startswith("/static/chat/sess1/")
    assert url.endswith(".png")
    disk = tmp_path / url.removeprefix("/static/")
    assert disk.is_file()
    assert disk.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_message_with_image_sends_photo(client, patch_redis, tmp_path, monkeypatch):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    img_dir = tmp_path / "chat" / "sess1"
    img_dir.mkdir(parents=True)
    path = img_dir / "a.png"
    path.write_bytes(_PNG)

    send_photo = AsyncMock()
    send_msg = AsyncMock()
    with (
        patch("api.routes.chat._send_telegram_photo", send_photo),
        patch("api.routes.chat._send_telegram", send_msg),
        patch("api.routes.chat._resolve_owner", new=AsyncMock(return_value=("x", 1))),
        patch("api.routes.chat.NOTIFY_CHAT_ID", ""),
        patch("api.routes.chat.ADMIN_ID", ""),
        patch("api.routes.chat.BOT_TOKEN", "t"),
    ):
        resp = client.post(
            "/chat/message",
            json={
                "session_id": "sess1",
                "subdomain": "s",
                "link_id": "l",
                "trigger": "user",
                "text": "скрин",
                "image": "/static/chat/sess1/a.png",
            },
        )
    assert resp.status_code == 200
    assert send_photo.await_count == 1
    assert send_msg.await_count == 0
    kwargs = send_photo.await_args.kwargs
    assert kwargs["photo_path"].replace("\\", "/").endswith("chat/sess1/a.png")
    assert "скрин" in kwargs["caption"]


@pytest.mark.asyncio
async def test_script_trigger_keeps_session_lang_on_reply_button(client, patch_redis):
    from api.cache import create_chat_session

    await create_chat_session("sess-en", "s", "l", lang="en-IN", sys_lang="en-IN")
    send_msg = AsyncMock()
    with (
        patch("api.routes.chat._send_telegram", send_msg),
        patch("api.routes.chat._send_telegram_photo", AsyncMock()),
        patch("api.routes.chat._resolve_owner", new=AsyncMock(return_value=("x", 1))),
        patch("api.routes.chat.NOTIFY_CHAT_ID", ""),
        patch("api.routes.chat.ADMIN_ID", ""),
        patch("api.routes.chat.BOT_TOKEN", "t"),
        patch("api.routes.chat._detect_lang", return_value="ru"),
    ):
        resp = client.post(
            "/chat/message",
            json={
                "session_id": "sess-en",
                "subdomain": "s",
                "link_id": "l",
                "trigger": "open",
                "text": "Здравствуйте, я могу вам помочь чем-нибудь?",
            },
        )
    assert resp.status_code == 200
    kb = send_msg.await_args.kwargs["reply_markup"]
    data = kb["inline_keyboard"][0][0]["callback_data"]
    assert data.endswith(":en-IN")
    assert "wchat_reply:sess-en:en-IN" == data


def test_chat_session_does_not_leak_visitor_count(client, patch_redis):
    visitor = type("V", (), {"id": 12345})()
    with (
        patch("api.routes.chat._get_geo", new=AsyncMock(return_value=("x", "y"))),
        patch("api.routes.chat.get_session") as gs,
        patch(
            "api.routes.chat.get_or_create_visitor",
            new=AsyncMock(return_value=(visitor, True)),
        ),
    ):
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=object())
        cm.__aexit__ = AsyncMock(return_value=None)
        gs.return_value = cm
        resp = client.post(
            "/chat/session",
            json={"subdomain": "s", "link_id": "l", "lang": "en"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "visitor_id" not in data
    assert "is_new" not in data

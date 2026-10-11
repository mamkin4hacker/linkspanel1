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


def test_upload_rejects_non_image(client, patch_redis):
    resp = client.post(
        "/chat/upload",
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"session_id": "sess1"},
    )
    assert resp.status_code == 400


def test_upload_saves_png_and_returns_url(client, patch_redis, tmp_path, monkeypatch):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
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

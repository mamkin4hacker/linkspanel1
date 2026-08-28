from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from api.cache import get_cached, get_preview_config, set_cached
from api.renderer import render_page
from db.crud.links import get_link_by_subdomain_and_id, increment_visits
from db.session import get_session

router = APIRouter()

_SUPPORTED_LANGS = {
    "ru", "en", "de", "fr", "es", "it", "pt", "pl", "nl", "tr",
    "ar", "zh", "ja", "ko", "uk", "cs", "sv", "fi", "no", "da",
}


def detect_language(accept_language: str) -> str:
    """Return best-match language code from Accept-Language header."""
    if not accept_language:
        return "en"
    for part in accept_language.split(","):
        tag = part.strip().split(";")[0].strip().lower()
        lang = tag.split("-")[0]
        if lang in _SUPPORTED_LANGS:
            return lang
    return "en"


@router.get("/{link_id}")
async def serve_page(request: Request, link_id: str):
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("host", "")
    subdomain = host.split(".")[0]
    user_lang = detect_language(request.headers.get("accept-language", ""))

    if subdomain == "preview":
        config = await get_preview_config(link_id)
        if not config:
            raise HTTPException(status_code=404)
        config = {**config, "user_lang": user_lang}
        return HTMLResponse(render_page(config))

    cache_key = f"page:{subdomain}:{link_id}:{user_lang}"
    cached = await get_cached(cache_key)
    if cached:
        return HTMLResponse(cached)

    async with get_session() as session:
        link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
        if not link or not link.is_active:
            raise HTTPException(status_code=404)
        await increment_visits(session, link.id)
        config = {c.key: getattr(link.template, c.key) for c in link.template.__table__.columns}
        config["subdomain"] = link.subdomain
        config["link_id"] = link.link_id

    config["user_lang"] = user_lang
    html = render_page(config)
    await set_cached(cache_key, html, ttl=300)
    return HTMLResponse(html)

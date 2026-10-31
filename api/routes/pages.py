from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from api.cache import _PAGE_CACHE_VER, get_cached, get_preview_config, set_cached
from api.locale import parse_accept_language
from api.page_i18n import PAGE_STRINGS, overlay_custom, resolve_page_i18n
from api.renderer import render_page
from db.crud.links import get_link_by_subdomain_and_id, increment_visits
from db.session import get_session

router = APIRouter()


async def _with_i18n(config: dict, user_lang: str) -> tuple[dict, bool]:
    strings = overlay_custom(PAGE_STRINGS, config)
    i18n, complete = await resolve_page_i18n(strings, user_lang)
    return {**config, "user_lang": user_lang, "i18n": i18n}, complete


@router.get("/{link_id}")
async def serve_page(request: Request, link_id: str):
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("host", "")
    host = host.split(":")[0].lower().strip()
    host_parts = host.split(".") if host else []
    subdomain = host_parts[0] if host_parts else ""
    apex = ".".join(host_parts[1:]) if len(host_parts) > 1 else ""
    user_lang = parse_accept_language(request.headers.get("accept-language", ""))

    if subdomain == "preview":
        config = await get_preview_config(link_id)
        if not config:
            raise HTTPException(status_code=404)
        cfg, _ = await _with_i18n(config, user_lang)
        return HTMLResponse(render_page(cfg))

    cache_key = f"page:{subdomain}:{link_id}:{user_lang}:{_PAGE_CACHE_VER}"
    cached = await get_cached(cache_key)
    if cached:
        return HTMLResponse(cached)

    async with get_session() as session:
        link = await get_link_by_subdomain_and_id(
            session, subdomain, link_id, domain=apex or None
        )
        if not link or not link.is_active:
            raise HTTPException(status_code=404)
        await increment_visits(session, link.id)
        config = {c.key: getattr(link.template, c.key) for c in link.template.__table__.columns}
        config["subdomain"] = link.subdomain
        config["link_id"] = link.link_id

    cfg, complete = await _with_i18n(config, user_lang)
    html = render_page(cfg)
    if complete:
        await set_cached(cache_key, html, ttl=300)
    return HTMLResponse(html)

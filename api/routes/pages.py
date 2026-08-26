from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from api.cache import get_cached, get_preview_config, set_cached
from api.renderer import render_page
from db.crud.links import get_link_by_subdomain_and_id, increment_visits
from db.session import get_session

router = APIRouter()


@router.get("/{link_id}")
async def serve_page(request: Request, link_id: str):
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("host", "")
    subdomain = host.split(".")[0]

    if subdomain == "preview":
        config = await get_preview_config(link_id)
        if not config:
            raise HTTPException(status_code=404)
        return HTMLResponse(render_page(config))

    cache_key = f"page:{subdomain}:{link_id}"
    cached = await get_cached(cache_key)
    if cached:
        return HTMLResponse(cached)

    async with get_session() as session:
        link = await get_link_by_subdomain_and_id(session, subdomain, link_id)
        if not link or not link.is_active:
            raise HTTPException(status_code=404)
        await increment_visits(session, link.id)
        config = {c.key: getattr(link.template, c.key) for c in link.template.__table__.columns}

    html = render_page(config)
    await set_cached(cache_key, html, ttl=300)
    return HTMLResponse(html)

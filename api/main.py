import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.cache import init_redis
from api.hardening import install_log_redaction
from api.routes.pages import router as pages_router
from api.routes.submit import router as submit_router
from api.routes.chat import router as chat_router
from db.session import init_db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
install_log_redaction()


class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from api.hardening import allow_request, client_ip, limited_path

        try:
            bucket = limited_path(request.url.path)
            if bucket:
                ip = client_ip(request)
                if not await allow_request(ip, bucket):
                    return Response(status_code=429)
        except Exception:
            pass
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        try:
            del response.headers["server"]
        except KeyError:
            pass
        return response


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.mount(
    "/static",
    StaticFiles(directory=os.getenv("STATIC_DIR", "/app/static")),
    name="static",
)

app.add_middleware(CSPMiddleware)
app.include_router(submit_router)
app.include_router(chat_router)
app.include_router(pages_router)


@app.on_event("startup")
async def startup():
    install_log_redaction()
    await init_db()
    await init_redis()
    logger.info("App started. BOT_TOKEN set: %s, NOTIFY_CHAT_ID: %s, ADMIN_ID: %s",
                bool(os.getenv("BOT_TOKEN")), os.getenv("NOTIFY_CHAT_ID"), os.getenv("ADMIN_ID"))

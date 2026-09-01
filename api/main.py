import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.cache import init_redis
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


class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self';"
        )
        return response


app = FastAPI(docs_url=None, redoc_url=None)

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
    await init_db()
    await init_redis()
    logger.info("App started. BOT_TOKEN set: %s, NOTIFY_CHAT_ID: %s, ADMIN_ID: %s",
                bool(os.getenv("BOT_TOKEN")), os.getenv("NOTIFY_CHAT_ID"), os.getenv("ADMIN_ID"))

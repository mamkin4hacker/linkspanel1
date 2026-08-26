import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.cache import init_redis
from api.routes.pages import router as pages_router
from db.session import init_db


class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'unsafe-inline'; "
            "script-src 'none'; "
            "img-src 'self' data:; "
            "connect-src 'none';"
        )
        return response


app = FastAPI(docs_url=None, redoc_url=None)

app.mount(
    "/static",
    StaticFiles(directory=os.getenv("STATIC_DIR", "/app/static")),
    name="static",
)

app.add_middleware(CSPMiddleware)
app.include_router(pages_router)


@app.on_event("startup")
async def startup():
    await init_db()
    await init_redis()

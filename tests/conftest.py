import os
import asyncio

import pytest
import pytest_asyncio

# Set env vars before any app imports
os.environ.setdefault("TEMPLATES_DIR", str(os.path.join(os.path.dirname(__file__), "..", "templates")))
os.environ.setdefault("STATIC_DIR", str(os.path.join(os.path.dirname(__file__), "..", "static")))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://linkgen:strongpassword@localhost:5432/linkgen")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("PREVIEW_DOMAIN", "preview")


# ── pytest-asyncio mode ────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


# ── Redis mock ─────────────────────────────────────────────────────────────────

class FakeRedis:
    """In-memory Redis replacement for unit tests."""

    def __init__(self):
        self._store: dict = {}

    async def get(self, key):
        val = self._store.get(key)
        return val.encode() if isinstance(val, str) else val

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def patch_redis(fake_redis, monkeypatch):
    """Replace the module-level _redis in api.cache with FakeRedis.

    Not autouse — tests that need Redis mock must request this fixture explicitly.
    test_api.py manages its own Redis via client._module_redis / its local patch_redis.
    """
    import api.cache as cache_module
    monkeypatch.setattr(cache_module, "_redis", fake_redis)
    return fake_redis


# ── DB fixtures (used only in test_crud.py) ───────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create tables once per session, drop after."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from db.models import Base

    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """
    Provide an isolated session per test via nested transactions (savepoints).

    The outer connection holds an open transaction that is never committed.
    Each CRUD function that calls session.commit() will commit the savepoint
    only — the outer transaction rolls back everything at the end of the test.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with db_engine.connect() as conn:
        await conn.begin()
        # Use join_transaction_mode so that session.commit() commits the
        # savepoint, not the outer connection transaction.
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()

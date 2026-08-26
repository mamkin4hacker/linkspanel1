import json
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


def _make_null_session_cm():
    """Return an async context manager that yields a dummy session."""
    dummy = MagicMock()

    @asynccontextmanager
    async def _cm():
        yield dummy

    return _cm


@pytest.fixture(scope="module")
def client():
    """
    TestClient with all external deps mocked out.

    Uses a single FakeRedis instance for the whole module so that tests
    without an explicit `patch_redis` parameter still have a working Redis.
    get_session is patched to avoid any real DB engine creation on cache misses.
    """
    from fastapi.testclient import TestClient
    from tests.conftest import FakeRedis
    import api.cache as cache_module

    # Install FakeRedis before the app starts so get_cached/set_cached work.
    module_redis = FakeRedis()
    cache_module._redis = module_redis

    with (
        patch("db.session.init_db", new=AsyncMock()),
        patch("api.cache.init_redis", new=AsyncMock()),
        patch("api.routes.pages.get_session", new=_make_null_session_cm()),
        patch("api.routes.pages.get_link_by_subdomain_and_id", new=AsyncMock(return_value=None)),
        patch("api.routes.pages.increment_visits", new=AsyncMock()),
    ):
        from api.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            c._module_redis = module_redis
            yield c

    # Restore to None so other test modules don't inherit our FakeRedis.
    cache_module._redis = None


@pytest.fixture
def patch_redis(client):
    """Return the FakeRedis instance wired into the test client, cleared per test."""
    r = client._module_redis
    r.clear()
    return r


class TestServePage:
    def test_404_unknown_link(self, client):
        resp = client.get("/notexist", headers={"host": "test.localhost"})
        assert resp.status_code == 404

    def test_404_no_host(self, client):
        resp = client.get("/abc12345")
        assert resp.status_code == 404

    def test_csp_header_present(self, client):
        resp = client.get("/anything", headers={"host": "test.localhost"})
        assert "Content-Security-Policy" in resp.headers

    def test_csp_blocks_scripts(self, client):
        resp = client.get("/anything", headers={"host": "test.localhost"})
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "script-src 'none'" in csp

    def test_preview_404_unknown_token(self, client, patch_redis):
        resp = client.get("/unknowntoken", headers={"host": "preview.localhost"})
        assert resp.status_code == 404

    def test_preview_renders_from_redis(self, client, patch_redis):
        config = {
            "bg_color": "#ffffff",
            "text_color": "#000000",
            "font_family": "Inter, sans-serif",
            "title": "Preview Test",
            "description": "Hello preview",
            "button_text": "",
            "button_url": "",
            "favicon_url": "",
            "custom_css": "",
        }
        patch_redis._store["preview_token:mytoken"] = "42"
        patch_redis._store["preview:42"] = json.dumps(config)

        resp = client.get("/mytoken", headers={"host": "preview.localhost"})
        assert resp.status_code == 200
        assert "Preview Test" in resp.text
        assert "Hello preview" in resp.text

    def test_preview_returns_html_content_type(self, client, patch_redis):
        config = {
            "bg_color": "#ffffff", "text_color": "#000000",
            "font_family": "Inter", "title": "T", "description": "",
            "button_text": "", "button_url": "", "favicon_url": "", "custom_css": "",
        }
        patch_redis._store["preview_token:tok2"] = "99"
        patch_redis._store["preview:99"] = json.dumps(config)

        resp = client.get("/tok2", headers={"host": "preview.localhost"})
        assert "text/html" in resp.headers.get("content-type", "")

    def test_cached_page_served(self, client, patch_redis):
        cached_html = "<html><body>cached</body></html>"
        patch_redis._store["page:cachedpage:abc12345"] = cached_html

        resp = client.get("/abc12345", headers={"host": "cachedpage.localhost"})
        assert resp.status_code == 200
        assert "cached" in resp.text

    def test_x_forwarded_host_used_over_host(self, client, patch_redis):
        cached_html = "<html><body>forwarded</body></html>"
        patch_redis._store["page:realhost:xyz99"] = cached_html

        resp = client.get(
            "/xyz99",
            headers={"host": "proxy.localhost", "X-Forwarded-Host": "realhost.domain.com"},
        )
        assert resp.status_code == 200
        assert "forwarded" in resp.text

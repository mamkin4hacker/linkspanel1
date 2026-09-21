import json
from unittest.mock import patch

from bot.utils.nginx_conf import _reload_nginx_sync, write_domain_conf, remove_domain_conf


def test_reload_fails_without_socket(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.utils.nginx_conf._DOCKER_SOCK", str(tmp_path / "missing.sock"))
    ok, err = _reload_nginx_sync()
    assert ok is False
    assert "сокет" in err.lower()


def test_reload_via_docker_api_success(tmp_path, monkeypatch):
    sock = tmp_path / "docker.sock"
    sock.write_bytes(b"")
    monkeypatch.setattr("bot.utils.nginx_conf._DOCKER_SOCK", str(sock))

    calls = []

    def fake_request(method, path, body=None, timeout=15):
        calls.append((method, path, body))
        if method == "GET" and path.startswith("/containers/json"):
            return 200, json.dumps([{"Id": "abc123", "Names": ["/app-nginx-1"]}]).encode()
        if method == "POST" and path.endswith("/exec"):
            assert body["Cmd"] == ["nginx", "-s", "reload"]
            return 201, json.dumps({"Id": "exec1"}).encode()
        if method == "POST" and path == "/exec/exec1/start":
            return 200, b""
        if method == "GET" and path == "/exec/exec1/json":
            return 200, json.dumps({"ExitCode": 0}).encode()
        return 500, b"unexpected"

    with patch("bot.utils.nginx_conf._docker_request", side_effect=fake_request):
        ok, err = _reload_nginx_sync()
    assert ok is True
    assert err == ""
    assert any(c[0] == "POST" and c[1] == "/containers/abc123/exec" for c in calls)


def test_reload_finds_fallback_name_when_label_empty(tmp_path, monkeypatch):
    sock = tmp_path / "docker.sock"
    sock.write_bytes(b"")
    monkeypatch.setattr("bot.utils.nginx_conf._DOCKER_SOCK", str(sock))

    def fake_request(method, path, body=None, timeout=15):
        if method == "GET" and path.startswith("/containers/json"):
            return 200, b"[]"
        if method == "GET" and path == "/containers/app-nginx-1/json":
            return 200, b"{}"
        if method == "POST" and "/containers/app-nginx-1/exec" in path:
            return 201, json.dumps({"Id": "exec2"}).encode()
        if method == "POST" and path == "/exec/exec2/start":
            return 200, b""
        if method == "GET" and path == "/exec/exec2/json":
            return 200, json.dumps({"ExitCode": 0}).encode()
        return 404, b"no"

    with patch("bot.utils.nginx_conf._docker_request", side_effect=fake_request):
        ok, err = _reload_nginx_sync()
    assert ok is True, err


def test_remove_domain_conf_deletes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.utils.nginx_conf.NGINX_DOMAINS_DIR", str(tmp_path))
    write_domain_conf("example.com")
    assert (tmp_path / "example.com.conf").exists()
    assert remove_domain_conf("example.com") is True
    assert not (tmp_path / "example.com.conf").exists()
    assert remove_domain_conf("example.com") is False

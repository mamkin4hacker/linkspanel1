import os
from pathlib import Path

from bot.utils import nginx_conf


def test_write_domain_conf_contains_server_name(tmp_path, monkeypatch):
    monkeypatch.setattr(nginx_conf, "NGINX_DOMAINS_DIR", str(tmp_path))
    nginx_conf.write_domain_conf("example.com")
    conf = (tmp_path / "example.com.conf").read_text(encoding="utf-8")
    assert "server_name example.com *.example.com;" in conf
    assert "ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem" in conf


def test_site_conf_includes_generated_domain_blocks():
    site = Path(__file__).resolve().parents[1] / "nginx" / "site.conf"
    text = site.read_text(encoding="utf-8")
    assert "include /etc/nginx/conf.d/domains/*.conf;" in text

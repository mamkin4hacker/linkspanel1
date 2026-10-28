import base64
import os
import re

from jinja2 import Environment, FileSystemLoader

_env = Environment(
    loader=FileSystemLoader(os.getenv("TEMPLATES_DIR", "/app/templates")),
    autoescape=True,
)

_CSS_BLACKLIST = re.compile(r'(url\s*\(|@import|expression\s*\()', re.IGNORECASE)
_HTML_COMMENT = re.compile(r"<!--(?!\[if)[\s\S]*?-->")
_BETWEEN_TAGS = re.compile(r">\s+<")
_SCRIPT_TAG = re.compile(
    r"<script(\b[^>]*)>([\s\S]*?)</script>",
    re.IGNORECASE,
)
_ATOB_PAYLOAD = re.compile(r'atob\("([A-Za-z0-9+/=]+)"\)')


def sanitize_css(css: str) -> str:
    return _CSS_BLACKLIST.sub("/* blocked */", css)


def minify_html(html: str) -> str:
    html = _HTML_COMMENT.sub("", html)
    html = _BETWEEN_TAGS.sub("><", html)
    return html.strip()


def pack_inline_scripts(html: str) -> str:
    def _pack(match: re.Match) -> str:
        attrs, body = match.group(1), match.group(2)
        lower_attrs = attrs.lower()
        if "src=" in lower_attrs:
            return match.group(0)
        if "type=" in lower_attrs and "javascript" not in lower_attrs:
            return match.group(0)
        src = body.strip()
        if not src:
            return match.group(0)
        payload = base64.b64encode(src.encode("utf-8")).decode("ascii")
        loader = (
            "(function(){var s=document.createElement('script');"
            f's.text=atob("{payload}");document.head.appendChild(s);}})();'
        )
        return f"<script{attrs}>{loader}</script>"

    return _SCRIPT_TAG.sub(_pack, html)


def unpack_packed_html(html: str) -> str:
    """Test helper: restore packed script bodies for assertions."""

    def _unpack(match: re.Match) -> str:
        try:
            return 'atob("' + match.group(1) + '")' + "\n" + base64.b64decode(
                match.group(1)
            ).decode("utf-8")
        except Exception:
            return match.group(0)

    return _ATOB_PAYLOAD.sub(_unpack, html)


def render_page(config: dict) -> str:
    safe_config = {**config}
    if safe_config.get("custom_css"):
        safe_config["custom_css"] = sanitize_css(safe_config["custom_css"])
    safe_config.pop("_sa_instance_state", None)
    html = _env.get_template("base.html").render(**safe_config)
    return pack_inline_scripts(minify_html(html))

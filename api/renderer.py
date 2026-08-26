import os
import re

from jinja2 import Environment, FileSystemLoader

_env = Environment(
    loader=FileSystemLoader(os.getenv("TEMPLATES_DIR", "/app/templates")),
    autoescape=True,
)

_CSS_BLACKLIST = re.compile(r'(url\s*\(|@import|expression\s*\()', re.IGNORECASE)


def sanitize_css(css: str) -> str:
    return _CSS_BLACKLIST.sub("/* blocked */", css)


def render_page(config: dict) -> str:
    safe_config = {**config}
    if safe_config.get("custom_css"):
        safe_config["custom_css"] = sanitize_css(safe_config["custom_css"])
    # strip SQLAlchemy internal keys
    safe_config.pop("_sa_instance_state", None)
    return _env.get_template("base.html").render(**safe_config)

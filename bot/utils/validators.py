import re

SUBDOMAIN_RE = re.compile(r'^[a-z0-9][a-z0-9\-]{1,58}[a-z0-9]$')
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
URL_RE = re.compile(r'^https?://.+')

RESERVED = {
    "www", "api", "admin", "mail", "ftp", "smtp", "ns1", "ns2",
    "preview", "static", "cdn", "app", "bot",
}

ALLOWED_FAVICON_MIMES = {"image/x-icon", "image/vnd.microsoft.icon", "image/png"}
MAX_FAVICON_BYTES = 1 * 1024 * 1024  # 1 MB


def validate_subdomain(value: str) -> str | None:
    """Return error message or None if valid."""
    v = value.strip().lower()
    if v in RESERVED:
        return "Это зарезервированное слово. Выбери другое название."
    if not SUBDOMAIN_RE.match(v):
        return (
            "Неверный формат. Используй только латиницу, цифры и дефис. "
            "Длина: от 2 до 60 символов. Начало и конец — не дефис."
        )
    return None


def validate_hex(value: str) -> str | None:
    if not HEX_RE.match(value.strip()):
        return "Неверный формат цвета. Введи HEX, например: #1a2b3c"
    return None


def validate_url(value: str) -> str | None:
    if not URL_RE.match(value.strip()):
        return "Неверный URL. Должен начинаться с http:// или https://"
    return None


def validate_favicon(mime: str, size: int) -> str | None:
    if mime not in ALLOWED_FAVICON_MIMES:
        return "Поддерживаются только .ico и .png файлы."
    if size > MAX_FAVICON_BYTES:
        return "Файл слишком большой. Максимум 1 МБ."
    return None

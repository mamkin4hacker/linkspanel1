import pytest
from bot.utils.validators import (
    validate_subdomain,
    validate_hex,
    validate_url,
    validate_favicon,
    MAX_FAVICON_BYTES,
)


class TestValidateSubdomain:
    def test_valid(self):
        assert validate_subdomain("my-page") is None

    def test_valid_numbers(self):
        assert validate_subdomain("page123") is None

    def test_valid_min_length(self):
        # regex: first char + {1,58} middle + last char = minimum 3 chars
        assert validate_subdomain("abc") is None

    def test_valid_max_length(self):
        assert validate_subdomain("a" * 60) is None

    def test_too_short(self):
        assert validate_subdomain("a") is not None

    def test_too_long(self):
        assert validate_subdomain("a" * 61) is not None

    def test_starts_with_hyphen(self):
        assert validate_subdomain("-mypage") is not None

    def test_ends_with_hyphen(self):
        assert validate_subdomain("mypage-") is not None

    def test_uppercase_normalised(self):
        # validator lowercases input before checking, so "MyPage" → "mypage" passes
        assert validate_subdomain("MyPage") is None

    def test_spaces(self):
        assert validate_subdomain("my page") is not None

    def test_cyrillic(self):
        assert validate_subdomain("страница") is not None

    def test_reserved_www(self):
        assert validate_subdomain("www") is not None

    def test_reserved_api(self):
        assert validate_subdomain("api") is not None

    def test_reserved_admin(self):
        assert validate_subdomain("admin") is not None

    def test_reserved_preview(self):
        assert validate_subdomain("preview") is not None

    def test_reserved_bot(self):
        assert validate_subdomain("bot") is not None

    def test_hyphen_in_middle(self):
        assert validate_subdomain("my-cool-page") is None

    def test_dot_not_allowed(self):
        assert validate_subdomain("my.page") is not None


class TestValidateHex:
    def test_valid_lowercase(self):
        assert validate_hex("#1a2b3c") is None

    def test_valid_uppercase(self):
        assert validate_hex("#FFFFFF") is None

    def test_valid_mixed(self):
        assert validate_hex("#aAbBcC") is None

    def test_missing_hash(self):
        assert validate_hex("ffffff") is not None

    def test_too_short(self):
        assert validate_hex("#fff") is not None

    def test_too_long(self):
        assert validate_hex("#1234567") is not None

    def test_invalid_chars(self):
        assert validate_hex("#gggggg") is not None

    def test_empty(self):
        assert validate_hex("") is not None

    def test_whitespace_stripped(self):
        # handler strips whitespace before calling
        assert validate_hex(" #ffffff ") is None  # strip happens inside validator


class TestValidateUrl:
    def test_https(self):
        assert validate_url("https://example.com") is None

    def test_http(self):
        assert validate_url("http://example.com") is None

    def test_with_path(self):
        assert validate_url("https://example.com/path?q=1") is None

    def test_ftp_rejected(self):
        assert validate_url("ftp://example.com") is not None

    def test_no_scheme(self):
        assert validate_url("example.com") is not None

    def test_empty(self):
        assert validate_url("") is not None

    def test_just_scheme(self):
        # regex requires at least one char after "://", so bare scheme is rejected
        assert validate_url("https://") is not None


class TestValidateFavicon:
    def test_valid_ico(self):
        assert validate_favicon("image/x-icon", 1024) is None

    def test_valid_ms_icon(self):
        assert validate_favicon("image/vnd.microsoft.icon", 1024) is None

    def test_valid_png(self):
        assert validate_favicon("image/png", 512 * 1024) is None

    def test_invalid_mime(self):
        assert validate_favicon("image/jpeg", 1024) is not None

    def test_invalid_gif(self):
        assert validate_favicon("image/gif", 1024) is not None

    def test_too_large(self):
        assert validate_favicon("image/png", MAX_FAVICON_BYTES + 1) is not None

    def test_exact_limit(self):
        assert validate_favicon("image/png", MAX_FAVICON_BYTES) is None

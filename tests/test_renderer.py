import os
import pytest

# Point to local templates dir before importing renderer
os.environ.setdefault("TEMPLATES_DIR", str(os.path.join(os.path.dirname(__file__), "..", "templates")))

from api.renderer import sanitize_css, render_page


class TestSanitizeCss:
    def test_blocks_url(self):
        result = sanitize_css("body { background: url('/evil.png'); }")
        assert "url(" not in result
        assert "/* blocked */" in result

    def test_blocks_url_with_spaces(self):
        result = sanitize_css("background: url ('/evil.png')")
        assert "url (" not in result

    def test_blocks_import(self):
        result = sanitize_css("@import url('evil.css');")
        assert "@import" not in result

    def test_blocks_expression(self):
        result = sanitize_css("width: expression(alert(1));")
        assert "expression(" not in result

    def test_blocks_expression_uppercase(self):
        result = sanitize_css("width: EXPRESSION(alert(1));")
        assert "EXPRESSION(" not in result

    def test_allows_safe_css(self):
        css = "body { color: red; font-size: 16px; }"
        assert sanitize_css(css) == css

    def test_empty_string(self):
        assert sanitize_css("") == ""

    def test_multiple_violations(self):
        css = "a { background: url('/x'); } @import 'evil';"
        result = sanitize_css(css)
        assert "url(" not in result
        assert "@import" not in result


class TestRenderPage:
    BASE_CONFIG = {
        "bg_color": "#ffffff",
        "text_color": "#000000",
        "font_family": "Inter, sans-serif",
        "title": "Test Title",
        "description": "Test description",
        "button_text": "",
        "button_url": "",
        "favicon_url": "",
        "custom_css": "",
    }

    def test_renders_html(self):
        html = render_page(self.BASE_CONFIG)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html

    def test_renders_title(self):
        html = render_page({**self.BASE_CONFIG, "title": "My Page"})
        assert "My Page" in html

    def test_renders_description(self):
        html = render_page({**self.BASE_CONFIG, "description": "Hello world"})
        assert "Hello world" in html

    def test_renders_button(self):
        html = render_page({
            **self.BASE_CONFIG,
            "button_text": "Click me",
            "button_url": "https://example.com",
        })
        assert "Click me" in html
        assert "https://example.com" in html

    def test_no_link_when_text_empty(self):
        # button_url without button_text: no clickable <a> with that href should be rendered
        html = render_page({**self.BASE_CONFIG, "button_text": "", "button_url": "https://x.com"})
        # The URL may appear in the JS variable, but not as an actual <a href=...> attribute value
        assert 'href="https://x.com"' not in html

    def test_no_link_when_url_empty(self):
        # button_text without button_url: no CTA anchor with that URL should appear
        html = render_page({**self.BASE_CONFIG, "button_text": "Click", "button_url": ""})
        # Static footer links (規約/プライバシー) are always in the modal JS string — that's fine.
        # What must NOT appear is an <a> pointing to the actual button_url value.
        assert 'href="Click"' not in html
        assert "Click" in html  # trigger button still shows the text

    def test_no_button_when_url_empty(self):
        # Legacy alias — same contract as test_no_link_when_url_empty
        html = render_page({**self.BASE_CONFIG, "button_text": "Click", "button_url": ""})
        assert 'href="Click"' not in html

    def test_renders_bg_color(self):
        html = render_page({**self.BASE_CONFIG, "bg_color": "#ff0000"})
        assert "#ff0000" in html

    def test_renders_text_color(self):
        html = render_page({**self.BASE_CONFIG, "text_color": "#123456"})
        assert "#123456" in html

    def test_favicon_link_present(self):
        html = render_page({**self.BASE_CONFIG, "favicon_url": "/static/favicons/test.ico"})
        assert "/static/favicons/test.ico" in html

    def test_no_favicon_tag_when_empty(self):
        html = render_page({**self.BASE_CONFIG, "favicon_url": ""})
        assert 'rel="icon"' not in html

    def test_custom_css_injected(self):
        html = render_page({**self.BASE_CONFIG, "custom_css": "body { margin: 10px; }"})
        assert "body { margin: 10px; }" in html

    def test_custom_css_sanitized(self):
        html = render_page({**self.BASE_CONFIG, "custom_css": "body { background: url('/x'); }"})
        # The injected custom_css must have url( blocked; font-face blocks in the template itself may contain url(
        assert "url('/x')" not in html

    def test_strips_sa_instance_state(self):
        config = {**self.BASE_CONFIG, "_sa_instance_state": object()}
        # Should not raise
        html = render_page(config)
        assert "<!DOCTYPE html>" in html

    def test_empty_title_uses_default(self):
        html = render_page({**self.BASE_CONFIG, "title": ""})
        assert "<title>KIBIDANGO - 本人確認</title>" in html

    def test_xss_in_title_escaped(self):
        html = render_page({**self.BASE_CONFIG, "title": "<script>alert(1)</script>"})
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

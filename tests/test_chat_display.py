from api.chat_display import bilingual_blocks, lang_flag, visitor_tag


def test_visitor_tag_prefixes_w():
    assert visitor_tag(475) == "#W475"
    assert visitor_tag("450") == "#W450"
    assert visitor_tag(None) == "#W?"
    assert visitor_tag("?") == "#W?"


def test_lang_flag():
    assert lang_flag("ru") == "🇷🇺"
    assert lang_flag("ja") == "🇯🇵"
    assert lang_flag("en-US") == "🇬🇧"


def test_bilingual_blocks_when_translated():
    out = bilingual_blocks("Привет", "こんにちは", "ru", "ja")
    assert "Оригинальное сообщение" in out
    assert "Переведенное сообщение" in out
    assert "Привет" in out
    assert "こんにちは" in out
    assert "🇷🇺" in out
    assert "🇯🇵" in out
    assert out.index("Оригинальное") < out.index("Переведенное")
    assert out.index("Привет") < out.index("こんにちは")
    assert "expandable" in out


def test_bilingual_blocks_same_text_is_plain():
    assert bilingual_blocks("hello", "hello", "en", "en") == "hello"

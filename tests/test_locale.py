from api.locale import locale_label, parse_accept_language, skip_translate


def test_empty_header_defaults_to_en():
    assert parse_accept_language("") == "en"
    assert parse_accept_language(None) == "en"


def test_picks_highest_q_and_keeps_region():
    assert parse_accept_language("fr;q=0.8, pt-BR;q=0.9, en;q=0.5") == "pt-BR"


def test_preserves_zh_tw():
    assert parse_accept_language("zh-TW,zh;q=0.9,en;q=0.8") == "zh-TW"


def test_normalizes_case():
    assert parse_accept_language("JA-jp") == "ja-JP"


def test_first_tag_without_q():
    assert parse_accept_language("ja,en-US;q=0.8") == "ja"


def test_unknown_language_is_kept_for_gemini():
    assert parse_accept_language("vi-VN,en;q=0.5") == "vi-VN"


def test_skip_translate_for_english_variants():
    assert skip_translate("en")
    assert skip_translate("en-US")
    assert skip_translate("en-GB")
    assert not skip_translate("pt-BR")
    assert not skip_translate("ja")


def test_locale_label_is_specific():
    assert "Brazilian" in locale_label("pt-BR")
    assert "Traditional" in locale_label("zh-TW")
    assert locale_label("ja") == "Japanese"

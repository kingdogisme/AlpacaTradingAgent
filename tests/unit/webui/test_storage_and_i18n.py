from __future__ import annotations

from webui.i18n import normalize_lang, t
from webui.utils.storage import get_default_api_keys, get_default_settings


def test_default_settings_are_copied_and_include_safe_trading_defaults():
    first = get_default_settings()
    second = get_default_settings()
    first["ticker_input"] = "MUTATED"

    assert second["ticker_input"] != "MUTATED"
    assert second["trading_horizon"] == "swing"
    assert second["trade_after_analyze"] is False
    assert second["checkpoint_enabled"] is False


def test_default_api_keys_are_empty_and_paper_trading_enabled():
    keys = get_default_api_keys()

    assert keys["openai"] == ""
    assert keys["alpaca-key"] == ""
    assert keys["alpaca-secret"] == ""
    assert keys["alpaca-paper"] is True


def test_i18n_falls_back_to_english_and_formats_values():
    assert normalize_lang("missing") == "en"
    assert t("missing", "alpaca.account.paper") == "Paper Trading"
    assert t("en", "alpaca.account.title", mode="Paper Trading") == "Alpaca Paper Trading Account"
    assert "模拟" in t("zh", "alpaca.account.paper")


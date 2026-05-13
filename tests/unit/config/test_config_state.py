from __future__ import annotations

import importlib

from tradingagents.dataflows import config as config_module


def test_set_config_get_config_returns_copy_and_isolates_mutation():
    original = config_module.get_config()
    try:
        config_module.set_config({"llm_provider": "google", "data_dir": "tmp-data"})

        first = config_module.get_config()
        first["llm_provider"] = "mutated"

        second = config_module.get_config()
        assert second["llm_provider"] == "google"
        assert config_module.DATA_DIR == "tmp-data"
    finally:
        config_module.set_config(original)


def test_set_config_merges_nested_dicts_without_dropping_siblings():
    original = config_module.get_config()
    try:
        config_module.set_config({"eval_neutral_band_bps": {"swing": 125}})

        updated = config_module.get_config()["eval_neutral_band_bps"]
        assert updated["swing"] == 125
        assert updated["position"] == original["eval_neutral_band_bps"]["position"]
        assert updated["trend"] == original["eval_neutral_band_bps"]["trend"]
    finally:
        config_module.set_config(original)


def test_tradingagents_env_overrides_are_typed(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "7")
    monkeypatch.setenv("TRADINGAGENTS_CHECKPOINT_ENABLED", "true")
    monkeypatch.setenv("TRADINGAGENTS_OUTPUT_LANGUAGE", "Chinese")

    import tradingagents.default_config as default_config

    reloaded = importlib.reload(default_config)
    try:
        assert reloaded.DEFAULT_CONFIG["max_debate_rounds"] == 7
        assert reloaded.DEFAULT_CONFIG["checkpoint_enabled"] is True
        assert reloaded.DEFAULT_CONFIG["output_language"] == "Chinese"
    finally:
        monkeypatch.delenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", raising=False)
        monkeypatch.delenv("TRADINGAGENTS_CHECKPOINT_ENABLED", raising=False)
        monkeypatch.delenv("TRADINGAGENTS_OUTPUT_LANGUAGE", raising=False)
        importlib.reload(default_config)


def test_default_output_language_is_zh_cn():
    import tradingagents.default_config as default_config

    assert default_config.DEFAULT_CONFIG["output_language"] == "zh-CN"


def test_runtime_api_keys_take_precedence_over_env_and_config(monkeypatch):
    original = config_module.get_config()
    original_runtime = config_module.get_runtime_api_keys()
    try:
        config_module.clear_runtime_api_keys()
        config_module.set_config({"openai_api_key": "config-key"})
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")

        assert config_module.get_openai_api_key() == "env-key"

        config_module.set_runtime_api_keys({"openai_api_key": "runtime-key"})
        assert config_module.get_openai_api_key() == "runtime-key"
    finally:
        config_module.clear_runtime_api_keys()
        if original_runtime:
            config_module.set_runtime_api_keys(original_runtime)
        config_module.set_config(original)


def test_empty_runtime_api_key_falls_back_to_env(monkeypatch):
    original_runtime = config_module.get_runtime_api_keys()
    try:
        config_module.clear_runtime_api_keys()
        config_module.set_runtime_api_keys({"alpaca_api_key": ""})
        monkeypatch.setenv("ALPACA_API_KEY", "env-alpaca")

        assert config_module.get_alpaca_api_key() == "env-alpaca"
    finally:
        config_module.clear_runtime_api_keys()
        if original_runtime:
            config_module.set_runtime_api_keys(original_runtime)

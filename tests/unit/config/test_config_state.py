from __future__ import annotations

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

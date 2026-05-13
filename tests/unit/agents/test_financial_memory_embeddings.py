from __future__ import annotations

from unittest.mock import patch

from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.dataflows import config as config_module


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_financial_memory_uses_google_embedding_provider(monkeypatch):
    original_config = config_module.get_config()
    try:
        config_module.set_config(
            {
                "embedding_provider": "google",
                "google_embedding_model": "gemini-embedding-001",
            }
        )
        monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

        with patch("tradingagents.agents.utils.memory.requests.post") as post:
            post.return_value = _FakeResponse({"embedding": {"values": [0.1, 0.2, 0.3]}})
            memory = FinancialSituationMemory("test_google_embedding_memory")

            assert memory.embeddings_enabled is True
            embedding = memory.get_embedding("market setup")

        assert embedding == [0.1, 0.2, 0.3]
        assert memory.embedding_provider == "google"
        post.assert_called_once()
        _, kwargs = post.call_args
        assert kwargs["params"] == {"key": "test-google-key"}
        assert kwargs["json"]["content"]["parts"][0]["text"] == "market setup"
        assert post.call_args.args[0].endswith("/models/gemini-embedding-001:embedContent")
    finally:
        config_module.set_config(original_config)


def test_financial_memory_accepts_gemini_provider_alias(monkeypatch):
    original_config = config_module.get_config()
    try:
        config_module.set_config(
            {
                "embedding_provider": "gemini",
                "google_embedding_model": "models/gemini-embedding-001",
            }
        )
        monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

        with patch("tradingagents.agents.utils.memory.requests.post") as post:
            post.return_value = _FakeResponse({"embedding": {"values": [0.3, 0.2, 0.1]}})
            memory = FinancialSituationMemory("test_gemini_alias_embedding_memory")
            embedding = memory.get_embedding("market setup")

        assert embedding == [0.3, 0.2, 0.1]
        assert memory.embedding_provider == "google"
        post.assert_called_once()
        assert post.call_args.args[0].endswith("/models/gemini-embedding-001:embedContent")
    finally:
        config_module.set_config(original_config)


def test_financial_memory_can_disable_embeddings():
    original_config = config_module.get_config()
    try:
        config_module.set_config({"embedding_provider": "disabled"})

        memory = FinancialSituationMemory("test_disabled_embedding_memory")

        assert memory.embedding_provider == "disabled"
        assert memory.embeddings_enabled is False
        assert memory.get_embedding("market setup") is None
    finally:
        config_module.set_config(original_config)

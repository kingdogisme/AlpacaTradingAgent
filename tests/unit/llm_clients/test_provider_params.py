from __future__ import annotations

from tradingagents.llm_clients.anthropic_client import AnthropicClient
from tradingagents.llm_clients.openai_client import OpenAIClient
from tradingagents.llm_clients.google_client import GoogleClient


def test_openai_compatible_client_passes_only_supported_runtime_params(monkeypatch):
    captured = {}

    class FakeChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI", FakeChat)

    client = OpenAIClient(
        "grok-4-0709",
        provider="xai",
        api_key="xai-key",
        reasoning_effort="high",
        callbacks=["cb"],
        temperature=0.4,
    )
    client.get_llm()

    assert captured["model"] == "grok-4-0709"
    assert captured["api_key"] == "xai-key"
    assert captured["reasoning_effort"] == "high"
    assert captured["callbacks"] == ["cb"]
    assert "temperature" not in captured


def test_google_client_keeps_thinking_level_provider_specific(monkeypatch):
    captured = {}

    class FakeGoogle:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI", FakeGoogle)

    GoogleClient("gemini-3.1-flash-lite-preview", api_key="google-key", thinking_level="high").get_llm()

    assert captured["google_api_key"] == "google-key"
    assert captured["thinking_level"] == "high"
    assert "reasoning_effort" not in captured


def test_anthropic_client_keeps_effort_provider_specific(monkeypatch):
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("tradingagents.llm_clients.anthropic_client.NormalizedChatAnthropic", FakeAnthropic)

    AnthropicClient("claude-sonnet-4-6", api_key="anthropic-key", effort="medium").get_llm()

    assert captured["api_key"] == "anthropic-key"
    assert captured["effort"] == "medium"
    assert "thinking_level" not in captured


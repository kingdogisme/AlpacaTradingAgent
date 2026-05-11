from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Iterable

import pytest


_TEST_ENV_DEFAULTS = {
    "PYTHON_DOTENV_DISABLED": "1",
    "TRADINGAGENTS_TEST_MODE": "1",
    "TRADINGAGENTS_DISABLE_NETWORK": "1",
    "OPENAI_API_KEY": "",
    "GOOGLE_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "XAI_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "DASHSCOPE_API_KEY": "",
    "ZHIPU_API_KEY": "",
    "OPENROUTER_API_KEY": "",
    "AZURE_OPENAI_API_KEY": "",
    "ALPACA_API_KEY": "",
    "ALPACA_SECRET_KEY": "",
    "FINNHUB_API_KEY": "",
    "FRED_API_KEY": "",
    "COINDESK_API_KEY": "",
    "ALPHA_VANTAGE_API_KEY": "",
}


def pytest_configure(config: pytest.Config) -> None:
    for key, value in _TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


@pytest.fixture(autouse=True)
def deterministic_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests isolated from local .env files, home dirs, and live service keys."""
    for key, value in _TEST_ENV_DEFAULTS.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("TRADINGAGENTS_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("TRADINGAGENTS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH", str(tmp_path / "memory" / "trading_memory.md"))


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Fail fast if deterministic tests accidentally reach the network."""
    external_allowed = (
        request.node.get_closest_marker("external") is not None
        and os.getenv("RUN_EXTERNAL_TESTS") == "1"
    )
    network_allowed = (
        request.node.get_closest_marker("network") is not None
        and os.getenv("RUN_EXTERNAL_TESTS") == "1"
    )
    if external_allowed or network_allowed:
        return

    original_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        raise AssertionError(f"External network access is disabled for deterministic tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    try:
        import requests
    except Exception:
        requests = None

    if requests is not None:
        def guarded_request(self: Any, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError(f"External HTTP access is disabled for deterministic tests: {method} {url}")

        monkeypatch.setattr(requests.sessions.Session, "request", guarded_request)

    yield


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.getenv("RUN_EXTERNAL_TESTS") == "1":
        return
    skip_external = pytest.mark.skip(reason="external smoke tests require RUN_EXTERNAL_TESTS=1")
    for item in items:
        if item.get_closest_marker("external") is not None or item.get_closest_marker("network") is not None:
            item.add_marker(skip_external)


@pytest.fixture
def isolated_config(tmp_path: Path) -> dict[str, Any]:
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config.update(
        {
            "results_dir": str(tmp_path / "results"),
            "data_cache_dir": str(tmp_path / "cache"),
            "memory_log_path": str(tmp_path / "memory" / "trading_memory.md"),
            "online_tools": False,
            "checkpoint_enabled": False,
            "llm_provider": "local_openai",
            "backend_url": "http://localhost:11434/v1",
            "quick_think_llm": "gpt-4.1",
            "deep_think_llm": "gpt-4.1",
        }
    )
    return config


class FakeMessage:
    def __init__(self, content: str, tool_calls: list[dict[str, Any]] | None = None):
        self.content = content
        self.additional_kwargs = {"tool_calls": tool_calls or []}
        self.tool_calls = tool_calls or []


class FakeLLM:
    """Small LangChain-compatible fake for agent and manager node tests."""

    def __init__(self, responses: Iterable[str] | None = None):
        self.responses = list(responses or ["Analysis.\nFINAL TRANSACTION PROPOSAL: **HOLD**"])
        self.prompts: list[Any] = []
        self.bound_tool_names: list[list[str]] = []

    def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> FakeMessage:
        self.prompts.append(prompt)
        content = self.responses.pop(0) if self.responses else "Analysis.\nFINAL TRANSACTION PROPOSAL: **HOLD**"
        return FakeMessage(content)

    def bind_tools(self, tools: list[Any]) -> Any:
        from langchain_core.messages import AIMessage
        from langchain_core.runnables import RunnableLambda

        self.bound_tool_names.append([getattr(tool, "name", str(tool)) for tool in tools])
        return RunnableLambda(lambda _messages: AIMessage(content=self.invoke(_messages).content))

    def with_structured_output(self, _schema: type[Any]) -> Any:
        raise NotImplementedError("FakeLLM uses free-text fallback by default")


class FakeTool:
    def __init__(self, name: str, output: str = "fake tool output"):
        self.name = name
        self.output = output
        self.calls: list[Any] = []

    def invoke(self, args: Any) -> str:
        self.calls.append(args)
        return self.output

    def run(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.output


class FakeMemory:
    def __init__(self, recommendations: list[str] | None = None):
        self.recommendations = recommendations or []
        self.queries: list[str] = []

    def get_memories(self, current_situation: str, n_matches: int = 1) -> list[dict[str, Any]]:
        self.queries.append(current_situation)
        return [
            {
                "matched_situation": f"memory-{index}",
                "recommendation": recommendation,
                "similarity_score": 1.0,
            }
            for index, recommendation in enumerate(self.recommendations[:n_matches], start=1)
        ]


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_memory() -> FakeMemory:
    return FakeMemory()

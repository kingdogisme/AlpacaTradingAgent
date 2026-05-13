from __future__ import annotations

from tradingagents.agents.utils import agent_utils


def test_fundamentals_timeout_fallback_uses_structured_data(monkeypatch):
    monkeypatch.setattr(
        agent_utils.interface,
        "build_openai_fundamentals_fallback",
        lambda ticker, curr_date, reason=None: (
            f"Fallback used because {reason} for {ticker} ({curr_date})."
        ),
    )

    result = agent_utils._build_timeout_fallback(
        "get_fundamentals_openai",
        {"ticker": "SNDK", "curr_date": "2026-05-11"},
        "TIMEOUT: Tool exceeded 165.0s",
    )

    assert result is not None
    assert "Fallback used because tool timeout before OpenAI fundamentals completed" in result
    assert "SNDK (2026-05-11)" in result

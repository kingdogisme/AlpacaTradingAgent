from __future__ import annotations

import os

import pytest


pytestmark = [pytest.mark.external, pytest.mark.network]


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for this external smoke test")
    return value


def _require_external_opt_in() -> None:
    if os.getenv("RUN_EXTERNAL_TESTS") != "1":
        pytest.skip("external smoke tests require RUN_EXTERNAL_TESTS=1")


def _openai_client_config() -> dict[str, str]:
    base_url = (
        os.getenv("OPENAI_SMOKE_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("TRADINGAGENTS_LLM_BACKEND_URL")
        or os.getenv("LOCAL_OPENAI_BASE_URL")
    )
    api_key = os.getenv("OPENAI_API_KEY")
    if base_url:
        return {"api_key": api_key or "local-llm", "base_url": base_url}

    if not api_key:
        pytest.skip(
            "OPENAI_API_KEY or a local OpenAI-compatible proxy URL "
            "(OPENAI_SMOKE_BASE_URL, OPENAI_BASE_URL, or TRADINGAGENTS_LLM_BACKEND_URL) "
            "is required for OpenAI smoke"
        )
    return {"api_key": api_key}


def test_sellthenews_stock_news_smoke():
    _require_external_opt_in()
    if not (os.getenv("SELLTHENEWS_API_KEY") or os.getenv("SELLTHENEWS_BASE_URL")):
        pytest.skip("SELLTHENEWS_API_KEY or SELLTHENEWS_BASE_URL is required for SellTheNews smoke")

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.integrations.sellthenews import SellTheNewsClient, looks_sparse

    client = SellTheNewsClient(
        os.getenv("SELLTHENEWS_BASE_URL") or DEFAULT_CONFIG.get("sellthenews_base_url"),
        float(os.getenv("SELLTHENEWS_TIMEOUT_SECONDS") or DEFAULT_CONFIG.get("sellthenews_timeout_seconds", 8)),
    )
    text = client.call_tool("get_stock_news", {"ticker": "AAPL"})

    assert text.strip()
    assert not looks_sparse(text)
    assert "rate limit" not in text.lower()


def test_alpha_vantage_company_overview_smoke():
    _require_external_opt_in()
    api_key = _require_env("ALPHA_VANTAGE_API_KEY")

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.integrations.alpha_vantage_mcp import AlphaVantageMCPClient, AlphaVantageMCPUnavailable

    client = AlphaVantageMCPClient(
        DEFAULT_CONFIG.get("alpha_vantage_mcp_base_url"),
        api_key,
        float(DEFAULT_CONFIG.get("alpha_vantage_mcp_timeout_seconds", 8)),
    )
    try:
        text = client.call_tool("COMPANY_OVERVIEW", {"symbol": "AAPL"})
    except AlphaVantageMCPUnavailable as exc:
        pytest.skip(f"Alpha Vantage unavailable or rate-limited: {exc}")

    assert "AAPL" in text or "Apple" in text


def test_sec_edgar_public_fundamentals_smoke(tmp_path):
    _require_external_opt_in()
    user_agent = _require_env("SEC_EDGAR_USER_AGENT")

    from tradingagents.dataflows.sec_edgar_utils import get_sec_edgar_fundamentals

    report = get_sec_edgar_fundamentals(
        "AAPL",
        "2026-05-20",
        config={
            "online_tools": True,
            "sec_edgar_enabled": True,
            "sec_edgar_user_agent": user_agent,
            "data_dir": str(tmp_path / "cache"),
            "sec_edgar_cache_ttl_hours": 24,
            "sec_edgar_mapping_cache_ttl_days": 7,
        },
    )

    assert "SEC EDGAR Official Fundamentals for AAPL" in report
    assert "CIK:" in report
    assert "official filing" in report.lower()


def test_alpaca_account_read_only_smoke():
    _require_external_opt_in()
    _require_env("ALPACA_API_KEY")
    _require_env("ALPACA_SECRET_KEY")

    from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client

    account = get_alpaca_trading_client().get_account()

    assert account
    assert getattr(account, "id", None) or getattr(account, "account_number", None)
    assert getattr(account, "trading_blocked", None) in {True, False}


def test_openai_minimal_response_smoke():
    _require_external_opt_in()
    openai = pytest.importorskip("openai")

    client = openai.OpenAI(**_openai_client_config())
    response = client.responses.create(
        model=os.getenv("OPENAI_SMOKE_MODEL", "gpt-4.1-mini"),
        input="Reply with exactly: OK",
        max_output_tokens=8,
    )

    assert "OK" in response.output_text

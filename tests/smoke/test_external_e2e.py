from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


pytestmark = [pytest.mark.external, pytest.mark.network, pytest.mark.slow]


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for this external E2E test")
    return value


def _require_external_e2e_opt_in() -> None:
    if os.getenv("RUN_EXTERNAL_TESTS") != "1":
        pytest.skip("external tests require RUN_EXTERNAL_TESTS=1")
    if os.getenv("RUN_EXTERNAL_E2E_TESTS") != "1":
        pytest.skip("external E2E tests require RUN_EXTERNAL_E2E_TESTS=1")


def _local_proxy_base_url() -> str | None:
    return (
        os.getenv("EXTERNAL_E2E_LLM_BACKEND_URL")
        or os.getenv("TRADINGAGENTS_LLM_BACKEND_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("LOCAL_OPENAI_BASE_URL")
    )


def _llm_config_from_env() -> dict[str, object]:
    provider = os.getenv("EXTERNAL_E2E_LLM_PROVIDER")
    base_url = _local_proxy_base_url()
    if base_url:
        return {
            "llm_provider": provider or "local_openai",
            "backend_url": base_url,
            "openai_use_local": True,
            "openai_base_url": base_url,
            "openai_api_key": os.getenv("OPENAI_API_KEY") or "local-llm",
        }

    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip(
            "OPENAI_API_KEY or a local OpenAI-compatible proxy URL "
            "(EXTERNAL_E2E_LLM_BACKEND_URL, TRADINGAGENTS_LLM_BACKEND_URL, or OPENAI_BASE_URL) "
            "is required for this external E2E test"
        )
    return {
        "llm_provider": provider or "openai",
        "backend_url": os.getenv("EXTERNAL_E2E_LLM_BACKEND_URL"),
        "openai_use_local": False,
        "openai_base_url": os.getenv("OPENAI_BASE_URL"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
    }


def test_external_graph_e2e_read_only_market_path(tmp_path, monkeypatch):
    """Run a minimal real-service graph path without allowing live orders."""
    _require_external_e2e_opt_in()
    llm_config = _llm_config_from_env()
    _require_env("ALPACA_API_KEY")
    _require_env("ALPACA_SECRET_KEY")

    from tradingagents.dataflows.alpaca_utils import AlpacaUtils
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    def forbidden_order(*_args, **_kwargs):
        raise AssertionError("External E2E smoke must remain read-only and must not submit orders")

    monkeypatch.setattr(AlpacaUtils, "place_market_order", staticmethod(forbidden_order))
    monkeypatch.setattr(AlpacaUtils, "close_position", staticmethod(forbidden_order), raising=False)
    monkeypatch.setattr(AlpacaUtils, "execute_trading_action", staticmethod(forbidden_order))

    config = {
        **DEFAULT_CONFIG,
        "results_dir": str(tmp_path / "eval_results"),
        "data_cache_dir": str(tmp_path / "cache"),
        "memory_log_path": str(tmp_path / "memory" / "trading_memory.md"),
        "episode_ledger_path": str(tmp_path / "eval" / "agent_eval.sqlite"),
        "alpha_discovery_db_path": str(tmp_path / "alpha_discovery.sqlite"),
        "llm_provider": llm_config["llm_provider"],
        "backend_url": llm_config["backend_url"],
        "openai_use_local": llm_config["openai_use_local"],
        "openai_base_url": llm_config["openai_base_url"],
        "quick_think_llm": os.getenv("EXTERNAL_E2E_QUICK_MODEL", os.getenv("OPENAI_SMOKE_MODEL", "gpt-4.1-mini")),
        "deep_think_llm": os.getenv("EXTERNAL_E2E_DEEP_MODEL", os.getenv("OPENAI_SMOKE_MODEL", "gpt-4.1-mini")),
        "quick_llm_params": {
            **DEFAULT_CONFIG.get("quick_llm_params", {}),
            "max_output_tokens": int(os.getenv("EXTERNAL_E2E_MAX_OUTPUT_TOKENS", "900")),
        },
        "deep_llm_params": {
            **DEFAULT_CONFIG.get("deep_llm_params", {}),
            "max_output_tokens": int(os.getenv("EXTERNAL_E2E_MAX_OUTPUT_TOKENS", "900")),
        },
        "online_tools": True,
        "checkpoint_enabled": False,
        "episode_ledger_enabled": True,
        "parallel_analysts": False,
        "parallel_risk_first_round": False,
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_iterations_per_agent": 1,
        "max_same_tool_call_repeats": 1,
        "max_recur_limit": 80,
        "trading_horizon": "swing",
        "allow_shorts": False,
        "trend_execution_enabled": False,
        "sellthenews_enabled": bool(os.getenv("SELLTHENEWS_API_KEY") or os.getenv("SELLTHENEWS_BASE_URL")),
        "news_global_openai_enabled": False,
        "social_openai_stock_news_enabled": False,
        "grounded_social_evidence_enabled": False,
        "openai_sources_policy": "disabled",
        "alpha_vantage_mcp_enabled": False,
        "sec_edgar_enabled": False,
        "finnhub_api_key": os.getenv("FINNHUB_API_KEY"),
        "alpaca_api_key": os.getenv("ALPACA_API_KEY"),
        "alpaca_secret_key": os.getenv("ALPACA_SECRET_KEY"),
        "openai_api_key": llm_config["openai_api_key"],
    }

    ticker = os.getenv("EXTERNAL_E2E_TICKER", "AAPL").upper()
    trade_date = os.getenv("EXTERNAL_E2E_TRADE_DATE", "2026-05-20")
    graph = TradingAgentsGraph(
        selected_analysts=["market"],
        config=config,
        debug=False,
    )

    final_state, final_signal = graph.propagate(ticker, trade_date)

    assert final_signal in {"BUY", "HOLD", "SELL", "LONG", "NEUTRAL", "SHORT"}
    assert "FINAL TRANSACTION PROPOSAL" in str(final_state.get("final_trade_decision", ""))
    assert final_state.get("market_report")

    run_files = list(
        Path(config["results_dir"]).glob(f"{ticker}/TradingAgentsStrategy_logs/runs/*.json")
    )
    assert run_files
    audit = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert audit["status"] == "completed"
    assert audit["summary"]["tool_events"] >= 1
    assert audit["summary"]["llm_call_events"] >= 1
    assert audit["summary"]["final_signal"] == final_signal

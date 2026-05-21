from __future__ import annotations

from tradingagents.dataflows import config as config_module
from tradingagents.dataflows import interface
from tradingagents.integrations.alpha_vantage_mcp import AlphaVantageMCPUnavailable


class FakeAlphaVantageClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return response


def _set_alpha_vantage_config(original_config, **overrides):
    config_module.set_config(
        {
            **original_config,
            "online_tools": True,
            "alpha_vantage_mcp_enabled": True,
            "alpha_vantage_fundamentals_enabled": True,
            "alpha_vantage_fallback_on_sparse": True,
            "alpha_vantage_api_key": "demo",
            **overrides,
        }
    )


def test_alpha_vantage_fundamentals_success(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_alpha_vantage_config(original_config)
        client = FakeAlphaVantageClient(
            {
                "COMPANY_OVERVIEW": '{"Symbol":"NVDA","PERatio":"42"}' * 20,
                "EARNINGS": '{"quarterlyEarnings":[{"surprisePercentage":"8"}]}' * 20,
                "EARNINGS_ESTIMATES": '{"estimates":[{"revenueEstimateAvg":"100"}]}' * 20,
                "INSIDER_TRANSACTIONS": '{"data":[{"transaction_type":"Sale"}]}' * 20,
                "INCOME_STATEMENT": '{"quarterlyReports":[{"totalRevenue":"1"}]}' * 20,
                "BALANCE_SHEET": '{"quarterlyReports":[{"cashAndCashEquivalentsAtCarryingValue":"1"}]}' * 20,
                "CASH_FLOW": '{"quarterlyReports":[{"operatingCashflow":"1"}]}' * 20,
            }
        )
        monkeypatch.setattr(interface, "_alpha_vantage_mcp_client", lambda _config: client)

        result = interface.get_alpha_vantage_fundamentals("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## Alpha Vantage Company Overview" in result
    assert "## Alpha Vantage Earnings" in result
    assert "## Alpha Vantage Insider Transactions" in result
    assert "freshness-unverified enrichment" in result
    assert [call[0] for call in client.calls] == [
        "COMPANY_OVERVIEW",
        "EARNINGS",
        "EARNINGS_ESTIMATES",
        "INSIDER_TRANSACTIONS",
        "INCOME_STATEMENT",
        "BALANCE_SHEET",
        "CASH_FLOW",
    ]
    assert client.calls[3][1]["from_date"] == "2026-02-11"


def test_alpha_vantage_rate_limit_falls_back(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_alpha_vantage_config(original_config)
        client = FakeAlphaVantageClient(
            {"COMPANY_OVERVIEW": AlphaVantageMCPUnavailable("standard API rate limit")}
        )
        monkeypatch.setattr(interface, "_alpha_vantage_mcp_client", lambda _config: client)
        monkeypatch.setattr(
            interface,
            "_build_empty_openai_fundamentals_fallback",
            lambda ticker, curr_date, reason: f"baseline fundamentals for {ticker}: {reason}",
        )

        result = interface.get_alpha_vantage_fundamentals("AAPL", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## Alpha Vantage fallback" in result
    assert "standard API rate limit" in result
    assert "baseline fundamentals for AAPL" in result

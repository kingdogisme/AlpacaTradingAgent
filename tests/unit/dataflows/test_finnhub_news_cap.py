from __future__ import annotations

from tradingagents.dataflows import config as config_module
from tradingagents.dataflows import interface


def test_finnhub_news_caps_cached_items(monkeypatch):
    original_config = config_module.get_config()
    try:
        config_module.set_config(
            {
                **original_config,
                "online_tools": False,
                "finnhub_news_max_items": 3,
                "finnhub_news_max_chars": 5000,
            }
        )
        monkeypatch.setattr(interface, "DATA_DIR", config_module.DATA_DIR)
        monkeypatch.setattr(
            interface,
            "get_data_in_range",
            lambda *_args, **_kwargs: {
                "2026-05-11": [
                    {"headline": f"Headline {idx}", "summary": "summary " * 10}
                    for idx in range(12)
                ]
            },
        )

        result = interface.get_finnhub_news("SNDK", "2026-05-11", 7)
    finally:
        config_module.set_config(original_config)
        monkeypatch.setattr(interface, "DATA_DIR", config_module.DATA_DIR)

    assert "output capped to 3 items / 5000 chars" in result
    assert result.count("### ") == 3
    assert "Headline 3" not in result


def test_finnhub_company_fundamentals_formats_live_payload(monkeypatch):
    original_config = config_module.get_config()
    try:
        config_module.set_config({**original_config, "online_tools": True})
        monkeypatch.setattr(
            interface,
            "fetch_company_profile_live",
            lambda ticker: {
                "name": "Li Auto Inc",
                "ticker": ticker,
                "exchange": "NASDAQ",
                "country": "CN",
                "finnhubIndustry": "Automobiles",
                "currency": "USD",
                "marketCapitalization": 30000,
            },
        )
        monkeypatch.setattr(
            interface,
            "fetch_basic_financials_live",
            lambda ticker, metric="all": {
                "metric": {
                    "peTTM": 20.5,
                    "psTTM": 1.2,
                    "grossMarginTTM": 18.6,
                    "revenueGrowthTTMYoy": -22.25,
                },
                "series": {
                    "annual": {
                        "eps": [
                            {"period": "2025-12-31", "v": 0.52},
                            {"period": "2024-12-31", "v": 3.77},
                        ],
                    },
                    "quarterly": {
                        "salesPerShare": [
                            {"period": "2025-12-31", "v": 1.72},
                        ],
                    },
                },
            },
        )
        monkeypatch.setattr(
            interface,
            "fetch_company_earnings_live",
            lambda ticker, limit=8: [
                {"period": "2025-12-31", "quarter": 4, "actual": 0, "estimate": 0.0255, "surprise": -0.0255, "surprisePercent": -100}
            ],
        )
        monkeypatch.setattr(
            interface,
            "fetch_recommendation_trends_live",
            lambda ticker: [{"period": "2026-05-01", "strongBuy": 7, "buy": 11, "hold": 15, "sell": 2, "strongSell": 1}],
        )
        monkeypatch.setattr(interface, "fetch_company_peers_live", lambda ticker: ["NIO", "XPEV"])

        result = interface.get_finnhub_company_fundamentals("LI", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "Finnhub Fundamentals for LI" in result
    assert "Li Auto Inc" in result
    assert "peTTM: 20.5" in result
    assert "Annual eps: 2025-12-31: 0.52" in result
    assert "strongBuy=7" in result
    assert "NIO, XPEV" in result

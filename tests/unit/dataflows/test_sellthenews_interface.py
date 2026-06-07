from __future__ import annotations

from tradingagents.dataflows import config as config_module
from tradingagents.dataflows import interface
from tradingagents.integrations.sellthenews import SellTheNewsUnavailable


class FakeSellTheNewsClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.chain_calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, list):
            return response.pop(0)
        return response

    def get_options_chain(self, ticker, *, expiration=None, greeks="gamma"):
        self.chain_calls.append((ticker, expiration, greeks))
        response = self.responses["get_options_chain"]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, list):
            return response.pop(0)
        return response


def _set_sellthenews_config(original_config, **overrides):
    config_module.set_config(
        {
            **original_config,
            "online_tools": True,
            "sellthenews_enabled": True,
            "sellthenews_news_enabled": True,
            "sellthenews_social_enabled": True,
            "sellthenews_macro_enabled": True,
            "sellthenews_dd_enabled": True,
            "sellthenews_dd_max_posts": 3,
            "sellthenews_dd_min_score": 0,
            "sellthenews_dd_min_comments": 0,
            "sellthenews_dd_max_chars": 6500,
            "sellthenews_options_enabled": False,
            "sellthenews_options_chain_api_enabled": False,
            "sellthenews_options_greeks": "gamma",
            "sellthenews_options_default_expiration": None,
            "sellthenews_options_max_chars": 4500,
            "sellthenews_fallback_on_sparse": True,
            **overrides,
        }
    )


def test_sellthenews_stock_news_success(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient(
            {
                "search_news": "Total articles: 12\n- NVDA search lead",
                "get_stock_news": [
                    "NVDA product cycle " * 40,
                    "NVDA older context " * 20,
                ],
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_stock_news("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## Enhanced News Source: SellTheNews" in result
    assert "## SellTheNews ticker search" in result
    assert "NVDA search lead" in result
    assert "NVDA product cycle" in result
    assert client.calls == [
        ("search_news", {"query": "NVDA stock", "limit": 12, "offset": 0, "sort": "time"}),
        ("get_stock_news", {"ticker": "NVDA", "limit": 20, "offset": 0}),
        ("get_stock_news", {"ticker": "NVDA", "limit": 10, "offset": 20}),
    ]


def test_sellthenews_stock_news_sparse_falls_back(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient(
            {
                "get_stock_news": "Total articles: 0",
                "search_news": ["No articles found", "No articles found"],
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(
            interface,
            "_build_empty_openai_stock_news_fallback",
            lambda ticker, curr_date: f"baseline news for {ticker} on {curr_date}",
        )

        result = interface.get_sellthenews_stock_news("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "company news coverage was sparse" in result
    assert "baseline news for NVDA on 2026-05-12" in result
    assert [call[0] for call in client.calls] == ["search_news", "get_stock_news", "search_news"]


def test_sellthenews_stock_news_error_falls_back(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient({"get_stock_news": SellTheNewsUnavailable("timeout")})
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(
            interface,
            "_build_empty_openai_stock_news_fallback",
            lambda ticker, curr_date: f"baseline news for {ticker}",
        )

        result = interface.get_sellthenews_stock_news("AAPL", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "timeout" in result
    assert "baseline news for AAPL" in result


def test_sellthenews_disabled_does_not_call_mcp(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_enabled=False)
        monkeypatch.setattr(
            interface,
            "_sellthenews_client",
            lambda _config: (_ for _ in ()).throw(AssertionError("MCP should not be called")),
        )
        monkeypatch.setattr(
            interface,
            "_build_empty_openai_stock_news_fallback",
            lambda ticker, curr_date: f"baseline news for {ticker}",
        )

        result = interface.get_sellthenews_stock_news("MSFT", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert result == "baseline news for MSFT"


def test_sellthenews_social_sentiment_success(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient(
            {
                "get_wsb_analysis": "Retail positioning and sentiment " * 40,
                "get_stock_news": "NVDA discussion catalyst " * 20,
                "search_news": "Total articles: 12\n- NVDA searched catalyst",
                "search_dd": (
                    '=== DD Search Results: "NVDA" ===\n'
                    "Showing 1 of 1\n\n"
                    "[1abc] NVDA AI thesis\n"
                    "  Tickers: NVDA\n"
                    "  score=42 | comments=12 | 2026-05-13 10:00:00 ET\n"
                ),
                "get_dd_post": "=== DD Post: NVDA AI thesis ===\n--- Fact Check ---\n1. [SUPPORTED] claim\n",
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_social_sentiment("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## Enhanced Social Sentiment Source: SellTheNews WSB" in result
    assert "## SellTheNews company-news context" in result
    assert "## SellTheNews ticker search context" in result
    assert "## SellTheNews WSB DD analysis" in result
    assert [call[0] for call in client.calls] == [
        "get_wsb_analysis",
        "get_stock_news",
        "search_news",
        "search_dd",
        "get_dd_post",
    ]


def test_sellthenews_social_uses_search_when_company_news_is_sparse(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient(
            {
                "get_wsb_analysis": "Retail positioning and sentiment " * 40,
                "get_stock_news": "Total articles: 0",
                "search_news": "Total articles: 8\n- LI delivery catalyst\n- LI product-cycle update",
                "search_dd": "=== DD Search Results: \"LI\" ===\nShowing 0 of 0\n",
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_social_sentiment("LI", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## Enhanced Social Sentiment Source: SellTheNews WSB" in result
    assert "## SellTheNews company-news context" in result
    assert "Total articles: 8" in result
    assert "WSB DD analysis unavailable or sparse: no matching DD posts found" in result
    assert "LI delivery catalyst" in result
    assert "## SellTheNews fallback" not in result
    assert [call[0] for call in client.calls] == [
        "get_wsb_analysis",
        "get_stock_news",
        "search_news",
        "search_dd",
    ]


def test_sellthenews_social_dd_error_does_not_fail_social_output(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient(
            {
                "get_wsb_analysis": "Retail positioning and sentiment " * 40,
                "get_stock_news": "SKM company catalyst " * 20,
                "search_news": "Total articles: 3\n- SKM searched catalyst",
                "search_dd": "[1abc] SKM Anthropic thesis\n  Tickers: SKM\n  score=7 | comments=8 | 2026-05-13 10:00:00 ET",
                "get_dd_post": SellTheNewsUnavailable("timeout"),
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_social_sentiment("SKM", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## Enhanced Social Sentiment Source: SellTheNews WSB" in result
    assert "SKM company catalyst" in result
    assert "WSB DD analysis unavailable or sparse: timeout" in result
    assert [call[0] for call in client.calls] == [
        "get_wsb_analysis",
        "get_stock_news",
        "search_news",
        "search_dd",
        "get_dd_post",
    ]


def test_sellthenews_social_dd_disabled_does_not_call_dd_tools(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_dd_enabled=False)
        client = FakeSellTheNewsClient(
            {
                "get_wsb_analysis": "Retail positioning and sentiment " * 40,
                "get_stock_news": "NVDA discussion catalyst " * 20,
                "search_news": "Total articles: 12\n- NVDA searched catalyst",
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_social_sentiment("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "SellTheNews WSB DD analysis" not in result
    assert [call[0] for call in client.calls] == ["get_wsb_analysis", "get_stock_news", "search_news"]


def test_sellthenews_social_dd_block_is_truncated(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_dd_max_chars=120)
        client = FakeSellTheNewsClient(
            {
                "get_wsb_analysis": "Retail positioning and sentiment " * 40,
                "get_stock_news": "NVDA discussion catalyst " * 20,
                "search_news": "Total articles: 12\n- NVDA searched catalyst",
                "search_dd": "[1abc] NVDA AI thesis\n  Tickers: NVDA\n  score=42 | comments=12 | 2026-05-13 10:00:00 ET",
                "get_dd_post": "Long DD body " * 80,
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_social_sentiment("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    dd_block = result.split("## SellTheNews WSB DD analysis", 1)[1]
    assert len(dd_block.split("\n\n## ", 1)[0]) < 180
    assert "..." in dd_block


def test_sellthenews_stock_news_search_first_for_small_caps(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient(
            {
                "search_news": "Total articles: 41\n- Nio fresh catalyst\n- Nio product cycle",
                "get_stock_news": [
                    "Total articles: 23\n- NIO stale March article",
                    "No articles found",
                ],
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_stock_news("NIO", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews ticker search" in result
    assert "Total articles: 41" in result
    assert "Nio fresh catalyst" in result
    assert "## Enhanced News Source: SellTheNews" in result
    assert client.calls[0] == (
        "search_news",
        {"query": "NIO stock", "limit": 12, "offset": 0, "sort": "time"},
    )


def test_sellthenews_macro_news_success(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient({"get_live_news": "FOMC rates liquidity " * 40})
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_macro_news("2026-05-12", "NVDA")
    finally:
        config_module.set_config(original_config)

    assert "## Enhanced Macro/Market News Source: SellTheNews" in result
    assert "FOMC rates liquidity" in result
    assert client.calls == [
        (
            "get_live_news",
            {"limit": 5, "offset": 0, "marketOnly": True, "lang": "en"},
        )
    ]


def test_sellthenews_macro_news_includes_company_identity(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config)
        client = FakeSellTheNewsClient({"get_live_news": "market regime update " * 40})
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(
            interface,
            "fetch_company_profile_live",
            lambda ticker: {
                "name": "Figma, Inc.",
                "ticker": ticker,
                "finnhubIndustry": "Software",
                "exchange": "NYSE",
                "country": "US",
            },
        )
        interface._COMPANY_PROFILE_CACHE.clear()

        result = interface.get_sellthenews_macro_news("2026-05-17", "FIG")
    finally:
        config_module.set_config(original_config)
        interface._COMPANY_PROFILE_CACHE.clear()

    assert "Ticker context: FIG: Figma, Inc.; industry=Software" in result
    assert "not ticker letters as a sector proxy" in result


def test_sellthenews_options_data_success(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_options_enabled=True)
        client = FakeSellTheNewsClient(
            {
                "get_options_data": (
                    "=== Options Data: NVDA ===\n"
                    "Spot Price: $120.00\n"
                    "Selected Expiration: 2026-05-15\n"
                    "Gamma Flip: $118\n\n"
                    "Call Wall: $125\n"
                    "Put Wall: $115\n"
                    "Max Pain: $121\n\n"
                    "--- GAMMA Exposure ---\n"
                    "$positive: 121, 125\n"
                    "$negative: 115, 118\n"
                    "$net: 121\n"
                )
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(interface, "_alpaca_mid_quote", lambda ticker: 119.5)

        result = interface.get_sellthenews_options_data("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews Options Positioning" in result
    assert "Selected Expiration: 2026-05-15" in result
    assert "Gamma Flip: $118" in result
    assert "Data quality: spot, selected expiration, required levels, and exposure fields were present." in result
    assert client.calls == [
        ("get_options_data", {"ticker": "NVDA", "greeks": "gamma"})
    ]


def test_sellthenews_options_chain_api_success(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(
            original_config,
            sellthenews_options_enabled=True,
            sellthenews_options_chain_api_enabled=True,
        )
        client = FakeSellTheNewsClient(
            {
                "get_options_chain": {
                    "ok": True,
                    "ticker": "NVDA",
                    "expiration_dates": ["2026-05-15", "2026-05-22"],
                    "selected_exp": "2026-05-15",
                    "updated_at": "2026-05-12T20:00:00Z",
                    "expiration": {
                        "spot": 220.88,
                        "forward_price": 220.9,
                        "implied_move_abs": 4.1,
                        "implied_move_pct": 1.86,
                        "total_call_oi": 117535,
                        "total_put_oi": 74676,
                        "pc_oi_ratio": 0.64,
                        "call_wall": 220,
                        "call_wall_oi": 23291,
                        "put_wall": 180,
                        "put_wall_oi": 7853,
                        "max_pain": 212.5,
                        "gamma_flip": 217.5,
                        "net_gex": 168678205.9,
                        "oi_source": "oi",
                        "insights": [
                            {
                                "title": "Positive Gamma Environment",
                                "text": "Dealers are long gamma.",
                            }
                        ],
                        "gex_by_strike": {
                            "217.5": 5626170.66,
                            "220.0": 73257612.23,
                            "210.0": -2359386.44,
                        },
                        "greeks_exposure": {
                            "gamma": {
                                "positive": {"220.0": 150155.06},
                                "negative": {"210.0": -4842.41},
                                "net": {"220.0": 150155.06, "210.0": -4842.41},
                            }
                        },
                    },
                }
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(interface, "_alpaca_mid_quote", lambda ticker: 220.0)

        result = interface.get_sellthenews_options_data("NVDA", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews Options Positioning" in result
    assert "Source: SellTheNews options chain API" in result
    assert "Selected Expiration: 2026-05-15" in result
    assert "Gamma Flip: $217.5" in result
    assert "Required Positioning Levels:" in result
    assert "- Call Wall: $220" in result
    assert "- Put Wall: $180" in result
    assert "- Max Pain: $212.5" in result
    assert "Net GEX: 168.7M" in result
    assert "Positive GEX strikes: $220 (73.3M)" in result
    assert "positive: $220 (150.2K)" in result
    assert "SellTheNews fallback" not in result
    assert client.chain_calls == [("NVDA", None, "gamma")]
    assert client.calls == []


def test_sellthenews_options_disabled_does_not_call_mcp(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_options_enabled=False)
        monkeypatch.setattr(
            interface,
            "_sellthenews_client",
            lambda _config: (_ for _ in ()).throw(AssertionError("MCP should not be called")),
        )

        result = interface.get_sellthenews_options_data("SPY", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "options data source is disabled" in result


def test_sellthenews_options_error_falls_back(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_options_enabled=True)
        client = FakeSellTheNewsClient({"get_options_data": SellTheNewsUnavailable("timeout")})
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)

        result = interface.get_sellthenews_options_data("AAPL", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "timeout" in result


def test_sellthenews_options_crypto_not_applicable(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_options_enabled=True)
        monkeypatch.setattr(
            interface,
            "_sellthenews_client",
            lambda _config: (_ for _ in ()).throw(AssertionError("MCP should not be called")),
        )

        result = interface.get_sellthenews_options_data("BTC/USD", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "not applicable to crypto" in result


def test_sellthenews_options_sparse_output_is_fallback_labeled(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(original_config, sellthenews_options_enabled=True)
        client = FakeSellTheNewsClient(
            {
                "get_options_data": (
                    "=== Options Data: SPY ===\n"
                    "Spot Price: $738.19\n"
                    "Selected Expiration: 2026-05-13\n"
                    "Gamma Flip: $645\n\n"
                    "--- GAMMA Exposure ---\n"
                    "$positive: \n"
                    "$negative: \n"
                    "$net: \n"
                )
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(interface, "_alpaca_mid_quote", lambda ticker: 738.0)

        result = interface.get_sellthenews_options_data("SPY", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "options exposure data was sparse" in result
    assert "SellTheNews Options Positioning" in result
    assert "required options levels are incomplete" in result
    assert "exposure rows are sparse or empty" in result


def test_sellthenews_options_chain_missing_required_levels_is_fallback_labeled(monkeypatch):
    original_config = config_module.get_config()
    try:
        _set_sellthenews_config(
            original_config,
            sellthenews_options_enabled=True,
            sellthenews_options_chain_api_enabled=True,
        )
        client = FakeSellTheNewsClient(
            {
                "get_options_chain": {
                    "ok": True,
                    "ticker": "AVGO",
                    "expiration_dates": ["2026-05-15"],
                    "selected_exp": "2026-05-15",
                    "expiration": {
                        "spot": 1200,
                        "gamma_flip": 1190,
                        "gex_by_strike": {"1200": 1000000},
                    },
                }
            }
        )
        monkeypatch.setattr(interface, "_sellthenews_client", lambda _config: client)
        monkeypatch.setattr(interface, "_alpaca_mid_quote", lambda ticker: 1200.0)

        result = interface.get_sellthenews_options_data("AVGO", "2026-05-12")
    finally:
        config_module.set_config(original_config)

    assert "## SellTheNews fallback" in result
    assert "required options levels are incomplete" in result
    assert "- Gamma Flip: $1190" in result
    assert "- Call Wall: unknown" in result
    assert "- Put Wall: unknown" in result
    assert "- Max Pain: unknown" in result

"""Public dataflow interface.

This package keeps the historical `tradingagents.dataflows.interface` import path
while grouping source-specific exports into smaller modules for agent navigation.
"""

from . import fundamentals, macro, market_data, news
from . import legacy as _legacy
from .news import (
    get_finnhub_news,
    get_coindesk_news,
    get_google_news,
    get_reddit_global_news,
    get_reddit_company_news,
    get_stock_news_openai,
    get_global_news_openai,
    get_sellthenews_stock_news,
    get_sellthenews_social_sentiment,
)

from .fundamentals import (
    build_openai_fundamentals_fallback,
    get_alpha_vantage_fundamentals,
    get_sec_edgar_fundamentals,
    get_finnhub_company_insider_sentiment,
    get_finnhub_company_insider_transactions,
    get_finnhub_company_fundamentals,
    get_simfin_balance_sheet,
    get_simfin_cashflow,
    get_simfin_income_statements,
    get_fundamentals_openai,
    get_defillama_fundamentals,
    get_earnings_calendar,
    get_earnings_surprise_analysis,
)

from .market_data import (
    get_alpaca_data_window,
    get_alpaca_data,
    get_sellthenews_options_data,
)

from .technical import (
    get_stock_stats_indicators_window,
    get_stockstats_indicator,
    get_stockstats_indicator_history,
    get_technical_brief,
    get_trend_brief,
)

from .macro import (
    _format_company_context,
    get_sellthenews_macro_news,
    get_macro_analysis,
    get_economic_indicators,
    get_yield_curve_analysis,
)
from .legacy import (
    _COMPANY_PROFILE_CACHE,
    _alpha_vantage_mcp_client,
    _sellthenews_client,
    AlpacaUtils,
    DATA_DIR,
    _alpaca_mid_quote,
    _build_empty_openai_fundamentals_fallback,
    _build_empty_openai_stock_news_fallback,
    fetch_basic_financials_live,
    fetch_company_earnings_live,
    fetch_company_peers_live,
    fetch_company_profile_live,
    fetch_recommendation_trends_live,
    get_data_in_range,
    get_sec_edgar_fundamentals_report,
)


def _sync_legacy_patches() -> None:
    """Keep old monkeypatch targets on this package compatible with legacy globals."""
    for name in (
        "_COMPANY_PROFILE_CACHE",
        "_alpha_vantage_mcp_client",
        "_sellthenews_client",
        "AlpacaUtils",
        "DATA_DIR",
        "fetch_company_profile_live",
        "fetch_basic_financials_live",
        "fetch_company_earnings_live",
        "fetch_company_peers_live",
        "fetch_recommendation_trends_live",
        "get_data_in_range",
        "get_sec_edgar_fundamentals_report",
        "_alpaca_mid_quote",
        "_build_empty_openai_fundamentals_fallback",
        "_build_empty_openai_stock_news_fallback",
    ):
        if name in globals():
            setattr(_legacy, name, globals()[name])


def get_alpha_vantage_fundamentals(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_alpha_vantage_fundamentals(*args, **kwargs)


def get_sec_edgar_fundamentals(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_sec_edgar_fundamentals(*args, **kwargs)


def get_finnhub_news(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_finnhub_news(*args, **kwargs)


def get_finnhub_company_fundamentals(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_finnhub_company_fundamentals(*args, **kwargs)


def get_alpaca_data_window(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_alpaca_data_window(*args, **kwargs)


def get_alpaca_data(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_alpaca_data(*args, **kwargs)


def get_sellthenews_stock_news(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_sellthenews_stock_news(*args, **kwargs)


def get_sellthenews_social_sentiment(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_sellthenews_social_sentiment(*args, **kwargs)


def get_sellthenews_macro_news(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_sellthenews_macro_news(*args, **kwargs)


def get_sellthenews_options_data(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy.get_sellthenews_options_data(*args, **kwargs)


def _format_company_context(*args, **kwargs):
    _sync_legacy_patches()
    return _legacy._format_company_context(*args, **kwargs)


news.get_finnhub_news = get_finnhub_news
news.get_sellthenews_stock_news = get_sellthenews_stock_news
news.get_sellthenews_social_sentiment = get_sellthenews_social_sentiment
fundamentals.get_alpha_vantage_fundamentals = get_alpha_vantage_fundamentals
fundamentals.get_sec_edgar_fundamentals = get_sec_edgar_fundamentals
fundamentals.get_finnhub_company_fundamentals = get_finnhub_company_fundamentals
market_data.get_alpaca_data_window = get_alpaca_data_window
market_data.get_alpaca_data = get_alpaca_data
market_data.get_sellthenews_options_data = get_sellthenews_options_data
macro._format_company_context = _format_company_context
macro.get_sellthenews_macro_news = get_sellthenews_macro_news

__all__ = [
    "get_finnhub_news",
    "get_coindesk_news",
    "get_google_news",
    "get_reddit_global_news",
    "get_reddit_company_news",
    "get_stock_news_openai",
    "get_global_news_openai",
    "get_sellthenews_stock_news",
    "get_sellthenews_social_sentiment",
    "build_openai_fundamentals_fallback",
    "get_alpha_vantage_fundamentals",
    "get_sec_edgar_fundamentals",
    "get_finnhub_company_insider_sentiment",
    "get_finnhub_company_insider_transactions",
    "get_finnhub_company_fundamentals",
    "get_simfin_balance_sheet",
    "get_simfin_cashflow",
    "get_simfin_income_statements",
    "get_fundamentals_openai",
    "get_defillama_fundamentals",
    "get_earnings_calendar",
    "get_earnings_surprise_analysis",
    "get_alpaca_data_window",
    "get_alpaca_data",
    "get_sellthenews_options_data",
    "get_stock_stats_indicators_window",
    "get_stockstats_indicator",
    "get_stockstats_indicator_history",
    "get_technical_brief",
    "get_trend_brief",
    "_format_company_context",
    "get_sellthenews_macro_news",
    "get_macro_analysis",
    "get_economic_indicators",
    "get_yield_curve_analysis",
    "_COMPANY_PROFILE_CACHE",
    "_alpha_vantage_mcp_client",
    "_sellthenews_client",
    "AlpacaUtils",
    "DATA_DIR",
    "fetch_company_profile_live",
    "fetch_basic_financials_live",
    "fetch_company_earnings_live",
    "fetch_company_peers_live",
    "fetch_recommendation_trends_live",
    "get_data_in_range",
    "get_sec_edgar_fundamentals_report",
    "_alpaca_mid_quote",
    "_build_empty_openai_fundamentals_fallback",
    "_build_empty_openai_stock_news_fallback",
]

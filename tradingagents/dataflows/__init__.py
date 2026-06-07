def _missing_optional(name: str, exc: Exception):
    def _raise(*args, **kwargs):
        raise ImportError(f"Optional dataflow dependency for {name} is unavailable: {exc}") from exc

    return _raise


try:
    from .finnhub_utils import get_data_in_range
except Exception as exc:  # pragma: no cover - depends on optional local env
    get_data_in_range = _missing_optional("get_data_in_range", exc)

try:
    from .googlenews_utils import getNewsData
except Exception as exc:  # pragma: no cover - depends on optional local env
    getNewsData = _missing_optional("getNewsData", exc)

try:
    from .reddit_utils import fetch_top_from_category
except Exception as exc:  # pragma: no cover - depends on optional local env
    fetch_top_from_category = _missing_optional("fetch_top_from_category", exc)

try:
    from .stockstats_utils import StockstatsUtils
except Exception as exc:  # pragma: no cover - depends on optional local env
    class StockstatsUtils:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError(f"Optional dataflow dependency for StockstatsUtils is unavailable: {exc}") from exc

try:
    from .alpaca_utils import AlpacaUtils
except Exception as exc:  # pragma: no cover - depends on optional local env
    class AlpacaUtils:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError(f"Optional dataflow dependency for AlpacaUtils is unavailable: {exc}") from exc

try:
    from .interface import (
        # News and sentiment functions
        get_finnhub_news,
        get_finnhub_company_insider_sentiment,
        get_finnhub_company_insider_transactions,
        get_google_news,
        get_reddit_global_news,
        get_reddit_company_news,
        # Financial statements functions
        get_simfin_balance_sheet,
        get_simfin_cashflow,
        get_simfin_income_statements,
        # Technical analysis functions
        get_stock_stats_indicators_window,
        get_stockstats_indicator,
        get_stockstats_indicator_history,
        get_technical_brief,
        get_trend_brief,
        # Market data functions
        get_alpaca_data_window,
        get_alpaca_data,
    )
except Exception as exc:  # pragma: no cover - depends on optional local env
    get_finnhub_news = _missing_optional("get_finnhub_news", exc)
    get_finnhub_company_insider_sentiment = _missing_optional("get_finnhub_company_insider_sentiment", exc)
    get_finnhub_company_insider_transactions = _missing_optional("get_finnhub_company_insider_transactions", exc)
    get_google_news = _missing_optional("get_google_news", exc)
    get_reddit_global_news = _missing_optional("get_reddit_global_news", exc)
    get_reddit_company_news = _missing_optional("get_reddit_company_news", exc)
    get_simfin_balance_sheet = _missing_optional("get_simfin_balance_sheet", exc)
    get_simfin_cashflow = _missing_optional("get_simfin_cashflow", exc)
    get_simfin_income_statements = _missing_optional("get_simfin_income_statements", exc)
    get_stock_stats_indicators_window = _missing_optional("get_stock_stats_indicators_window", exc)
    get_stockstats_indicator = _missing_optional("get_stockstats_indicator", exc)
    get_stockstats_indicator_history = _missing_optional("get_stockstats_indicator_history", exc)
    get_technical_brief = _missing_optional("get_technical_brief", exc)
    get_trend_brief = _missing_optional("get_trend_brief", exc)
    get_alpaca_data_window = _missing_optional("get_alpaca_data_window", exc)
    get_alpaca_data = _missing_optional("get_alpaca_data", exc)

# Ticker utilities for standardizing symbol formats
from .ticker_utils import (
    TickerUtils,
    normalize_ticker_for_logs,
    is_crypto_ticker,
    get_base_crypto_symbol,
    format_for_alpaca,
    format_for_openai_news,
)

__all__ = [
    # News and sentiment functions
    "get_finnhub_news",
    "get_finnhub_company_insider_sentiment",
    "get_finnhub_company_insider_transactions",
    "get_google_news",
    "get_reddit_global_news",
    "get_reddit_company_news",
    # Financial statements functions
    "get_simfin_balance_sheet",
    "get_simfin_cashflow",
    "get_simfin_income_statements",
    # Technical analysis functions
    "get_stock_stats_indicators_window",
    "get_stockstats_indicator",
    "get_stockstats_indicator_history",
    "get_technical_brief",
    "get_trend_brief",
    # Market data functions
    "get_alpaca_data_window",
    "get_alpaca_data",
    # Ticker utilities
    "TickerUtils",
    "normalize_ticker_for_logs",
    "is_crypto_ticker",
    "get_base_crypto_symbol",
    "format_for_alpaca",
    "format_for_openai_news",
]

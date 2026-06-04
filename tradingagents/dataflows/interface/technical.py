"""Compatibility exports for dataflow interface functions."""

from .legacy import (
    get_stock_stats_indicators_window,
    get_stockstats_indicator,
    get_stockstats_indicator_history,
    get_technical_brief,
    get_trend_brief,
)

__all__ = [
    "get_stock_stats_indicators_window",
    "get_stockstats_indicator",
    "get_stockstats_indicator_history",
    "get_technical_brief",
    "get_trend_brief",
]

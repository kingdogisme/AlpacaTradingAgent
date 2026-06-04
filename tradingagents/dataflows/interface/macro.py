"""Compatibility exports for dataflow interface functions."""

from .legacy import (
    _format_company_context,
    get_sellthenews_macro_news,
    get_macro_analysis,
    get_economic_indicators,
    get_yield_curve_analysis,
)

__all__ = [
    "_format_company_context",
    "get_sellthenews_macro_news",
    "get_macro_analysis",
    "get_economic_indicators",
    "get_yield_curve_analysis",
]

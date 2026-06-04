"""Compatibility exports for dataflow interface functions."""

from .legacy import (
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

__all__ = [
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
]

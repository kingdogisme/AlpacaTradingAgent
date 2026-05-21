from __future__ import annotations

import re


NON_STOCK_SYMBOLS = {
    # Indices and index-like symbols commonly surfaced in social feeds.
    "DJI",
    "NDX",
    "RUT",
    "SPX",
    "SPXW",
    "VIX",
    # Broad, sector, commodity, volatility, leveraged, and inverse ETFs/ETNs.
    "BNO",
    "DIA",
    "GLD",
    "IWM",
    "QQQ",
    "SLV",
    "SOXL",
    "SOXS",
    "SPXL",
    "SPXS",
    "SPY",
    "SQQQ",
    "TQQQ",
    "UCO",
    "UNG",
    "USO",
    "VTI",
    "VOO",
    "XBI",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
}

MACRO_OR_GENERIC_TERMS = {
    "AI",
    "ATH",
    "CEO",
    "CFO",
    "CPI",
    "DD",
    "DRAM",
    "EPS",
    "ETF",
    "GDP",
    "IPO",
    "M&A",
    "NAV",
    "PCE",
    "PPI",
    "PE",
    "SEC",
    "USA",
    "USD",
    "WSB",
}

UNSEASONED_IPO_SYMBOLS = {
    # Newly listed / not-yet-seasoned symbols are too noisy for ordinary AD
    # basket routing until broker metadata and first-session price history exist.
    "CBRS",
}

AMBIGUOUS_SYMBOL_CONTEXT = {
    "S": {
        "equity_terms": {
            "sentinelone",
            "sentinelone inc",
            "cybersecurity",
            "endpoint security",
        },
        "non_equity_terms": {
            "s&p",
            "sp500",
            "s and p",
            "s 500",
            "s&p 500",
            "standard & poor",
            "standard and poor",
        },
    },
    "I": {
        "equity_terms": {
            "intelsat",
            "intelsat s.a.",
            "satellite operator",
        },
        "non_equity_terms": {
            " i ",
            "i think",
            "i am",
            "ipo",
            "massacre",
            "opened",
            "opening",
        },
    },
    "WTI": {
        "equity_terms": {"w&t", "w&t offshore", "offshore"},
        "non_equity_terms": {
            "barrel",
            "brent",
            "commodity",
            "crude",
            "futures",
            "inventories",
            "inventory",
            "oil",
            "opec",
            "petroleum",
        },
    },
}

INITIAL_PUBLIC_OFFERING_TERMS = {
    "ipo",
    "priced",
    "pricing",
    "listing",
    "debut",
    "newly public",
}


def normalize_ticker(value: str) -> str:
    return str(value or "").strip().lstrip("$").upper()


def is_common_stock_candidate(ticker: str, *, context: str = "") -> bool:
    symbol = normalize_ticker(ticker)
    lowered_context = str(context or "").lower()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", symbol):
        return False
    if symbol in NON_STOCK_SYMBOLS or symbol in MACRO_OR_GENERIC_TERMS:
        return False
    if symbol in UNSEASONED_IPO_SYMBOLS:
        return False
    if _looks_like_unseasoned_ipo(symbol, lowered_context):
        return False
    ambiguous = AMBIGUOUS_SYMBOL_CONTEXT.get(symbol)
    if not ambiguous:
        return True

    equity_terms = ambiguous["equity_terms"]
    non_equity_terms = ambiguous["non_equity_terms"]
    has_equity_context = any(term in lowered_context for term in equity_terms)
    has_non_equity_context = any(re.search(rf"\b{re.escape(term)}\b", lowered_context) for term in non_equity_terms)

    if has_equity_context:
        return True
    if has_non_equity_context:
        return False

    # Ambiguous all-caps symbols without company context are too noisy for the
    # ordinary stock basket. They can be reconsidered once asset metadata is wired in.
    return False


def is_ambiguous_symbol(ticker: str) -> bool:
    return normalize_ticker(ticker) in AMBIGUOUS_SYMBOL_CONTEXT


def _looks_like_unseasoned_ipo(symbol: str, lowered_context: str) -> bool:
    if not lowered_context:
        return False
    symbol_near_context = re.search(rf"\b{re.escape(symbol.lower())}\b[\s\S]{{0,120}}\b(ipo|listing|debut)\b", lowered_context)
    context_near_symbol = re.search(rf"\b(ipo|listing|debut)\b[\s\S]{{0,120}}\b{re.escape(symbol.lower())}\b", lowered_context)
    has_ipo_language = bool(symbol_near_context or context_near_symbol)
    has_pricing_language = any(term in lowered_context for term in INITIAL_PUBLIC_OFFERING_TERMS)
    return has_ipo_language and has_pricing_language

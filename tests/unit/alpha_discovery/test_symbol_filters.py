from __future__ import annotations

from tradingagents.alpha_discovery.symbol_filters import is_common_stock_candidate


def test_symbol_filter_rejects_etfs_indices_and_macro_terms():
    for ticker in ("SPX", "BNO", "SLV", "SOXL", "QQQ", "SPY", "AI", "CPI"):
        assert not is_common_stock_candidate(ticker)


def test_symbol_filter_rejects_wti_when_context_is_crude_oil():
    assert not is_common_stock_candidate(
        "WTI",
        context="WTI crude oil inventories, OPEC headlines, and Brent futures drove energy discussion.",
    )


def test_symbol_filter_allows_wti_with_company_context():
    assert is_common_stock_candidate(
        "WTI",
        context="W&T Offshore earnings, production guidance, and balance sheet discussion.",
    )


def test_symbol_filter_rejects_s_when_context_is_sp500():
    assert not is_common_stock_candidate(
        "S",
        context="S&P 500 closed at a new high while market breadth remains poor.",
    )


def test_symbol_filter_allows_s_with_sentinelone_context():
    assert is_common_stock_candidate(
        "S",
        context="SentinelOne cybersecurity revenue growth and endpoint security demand.",
    )


def test_symbol_filter_rejects_new_ipo_context():
    assert not is_common_stock_candidate(
        "CBRS",
        context="CBRS Cerebras IPO priced at $185, listing on 5/14 after raising $5.55B.",
    )

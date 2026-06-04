from __future__ import annotations


def test_dataflows_interface_compatibility_exports():
    from tradingagents.dataflows import interface
    from tradingagents.dataflows.interface import fundamentals, macro, market_data, news, technical

    assert interface.get_finnhub_news is news.get_finnhub_news
    assert interface.get_alpaca_data is market_data.get_alpaca_data
    assert interface.get_technical_brief is technical.get_technical_brief
    assert interface.get_macro_analysis is macro.get_macro_analysis
    assert interface.get_sec_edgar_fundamentals is fundamentals.get_sec_edgar_fundamentals

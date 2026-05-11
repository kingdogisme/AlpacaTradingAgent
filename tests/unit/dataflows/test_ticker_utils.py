from __future__ import annotations

import pytest

from tradingagents.dataflows.ticker_utils import (
    TickerUtils,
    format_for_alpaca,
    format_for_openai_news,
    get_base_crypto_symbol,
    is_crypto_ticker,
    normalize_ticker_for_logs,
)


@pytest.mark.parametrize(
    ("raw", "alpaca", "openai", "yahoo", "display"),
    [
        ("btc/usd", "BTC/USD", "BTCUSD", "BTC-USD", "BTC/USD"),
        ("ETH-USD", "ETH/USD", "ETHUSD", "ETH-USD", "ETH/USD"),
        ("SOLUSDT", "SOL/USD", "SOLUSD", "SOL-USD", "SOL/USD"),
        ("AAPL", "AAPL", "AAPL", "AAPL", "AAPL"),
    ],
)
def test_ticker_formats_for_supported_apis(raw, alpaca, openai, yahoo, display):
    info = TickerUtils.standardize_ticker(raw)

    assert info["alpaca_format"] == alpaca
    assert info["openai_format"] == openai
    assert info["yahoo_format"] == yahoo
    assert info["display_format"] == display
    assert TickerUtils.convert_for_api(raw, "alpaca") == alpaca
    assert TickerUtils.convert_for_api(raw, "openai") == openai


def test_crypto_detection_and_base_symbol_helpers():
    assert is_crypto_ticker("BTC/USD")
    assert is_crypto_ticker("ETHUSDT")
    assert not is_crypto_ticker("MSFT")
    assert get_base_crypto_symbol("BTC/USD") == "BTC"
    assert format_for_alpaca("BTCUSD") == "BTC/USD"
    assert format_for_openai_news("BTC/USD") == "BTCUSD"
    assert normalize_ticker_for_logs("eth-usd") == "ETH/USD"


def test_empty_ticker_raises_clear_error():
    with pytest.raises(ValueError, match="Ticker cannot be empty"):
        TickerUtils.standardize_ticker("")


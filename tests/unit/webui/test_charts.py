from __future__ import annotations

import pandas as pd

from webui.utils.charts import _prepare_chart_timestamps, _stock_market_rangebreaks


def test_intraday_stock_timestamps_are_converted_to_market_time():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-05-11T13:30:00Z", "2026-05-11T20:00:00Z"]),
            "open": [10, 11],
            "high": [11, 12],
            "low": [9, 10],
            "close": [10.5, 11.5],
            "volume": [100, 200],
        }
    )

    prepared = _prepare_chart_timestamps(df, "SNDK", "1w")

    assert str(prepared["timestamp"].iloc[0]) == "2026-05-11 09:30:00"
    assert str(prepared["timestamp"].iloc[1]) == "2026-05-11 16:00:00"


def test_intraday_stock_rangebreaks_hide_regular_market_closure():
    rangebreaks = _stock_market_rangebreaks("SNDK", "1w")

    assert rangebreaks == [
        {"bounds": ["sat", "mon"]},
        {"bounds": [16, 9.5], "pattern": "hour"},
    ]


def test_crypto_charts_do_not_hide_market_hours():
    assert _stock_market_rangebreaks("BTC/USD", "1w") == []

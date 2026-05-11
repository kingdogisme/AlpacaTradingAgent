from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows import interface
from tradingagents.dataflows.config import get_config, set_config


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1100],
        }
    )


def test_alpaca_window_uses_curr_date_as_historical_end_date():
    original_config = get_config()
    set_config({**original_config, "online_tools": False})
    try:
        with patch.object(interface.AlpacaUtils, "get_stock_data", return_value=_bars()) as get_stock_data, patch.object(
            interface.AlpacaUtils, "get_latest_quote"
        ) as get_latest_quote:
            result = interface.get_alpaca_data_window("AAPL", "2024-01-03", look_back_days=5)

        get_stock_data.assert_called_once()
        assert get_stock_data.call_args.kwargs["start_date"] == "2023-12-29"
        assert get_stock_data.call_args.kwargs["end_date"] == "2024-01-03"
        assert "from 2023-12-29 to 2024-01-03" in result
        assert "Latest Quote" not in result
        get_latest_quote.assert_not_called()
    finally:
        set_config(original_config)


def test_alpaca_direct_data_skips_latest_quote_for_past_end_date():
    original_config = get_config()
    set_config({**original_config, "online_tools": True})
    try:
        with patch.object(interface.AlpacaUtils, "get_stock_data", return_value=_bars()), patch.object(
            interface.AlpacaUtils, "get_latest_quote"
        ) as get_latest_quote:
            result = interface.get_alpaca_data("AAPL", "2024-01-01", "2024-01-03")

        assert "from 2024-01-01 to 2024-01-03" in result
        assert "Latest Real-Time Quote" not in result
        get_latest_quote.assert_not_called()
    finally:
        set_config(original_config)

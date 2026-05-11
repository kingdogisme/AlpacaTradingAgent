from __future__ import annotations

from unittest.mock import patch

from tradingagents.dataflows.alpaca_utils import AlpacaUtils


def test_crypto_short_is_rejected_without_order_call():
    with patch.object(AlpacaUtils, "place_market_order") as place_order:
        result = AlpacaUtils.execute_trading_action(
            symbol="BTC/USD",
            current_position="NEUTRAL",
            signal="SHORT",
            dollar_amount=1000,
            allow_shorts=True,
        )

    assert not result["success"]
    assert result["actions"][0]["action"] == "open_short"
    assert "not supported for crypto" in result["actions"][0]["result"]["error"]
    place_order.assert_not_called()


def test_investment_buy_uses_crypto_notional_and_stock_quantity():
    with patch.object(AlpacaUtils, "place_market_order", return_value={"success": True}) as place_order:
        crypto_result = AlpacaUtils.execute_trading_action(
            symbol="BTC/USD",
            current_position="NEUTRAL",
            signal="BUY",
            dollar_amount=250,
            allow_shorts=False,
        )

    assert crypto_result["success"]
    place_order.assert_called_once_with("BTC/USD", "buy", notional=250)

    with patch.object(AlpacaUtils, "get_latest_quote", return_value={"bid_price": 50}), patch.object(
        AlpacaUtils, "place_market_order", return_value={"success": True}
    ) as place_order:
        stock_result = AlpacaUtils.execute_trading_action(
            symbol="AAPL",
            current_position="NEUTRAL",
            signal="BUY",
            dollar_amount=250,
            allow_shorts=False,
        )

    assert stock_result["success"]
    place_order.assert_called_once_with("AAPL", "buy", qty=5)


def test_sell_without_position_holds_without_order_call():
    with patch.object(AlpacaUtils, "close_position") as close_position:
        result = AlpacaUtils.execute_trading_action(
            symbol="AAPL",
            current_position="NEUTRAL",
            signal="SELL",
            dollar_amount=250,
            allow_shorts=False,
        )

    assert result["success"]
    assert result["actions"][0]["action"] == "hold"
    close_position.assert_not_called()


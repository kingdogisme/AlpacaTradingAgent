from __future__ import annotations

from typing import Any

from .broker import BrokerAdapter


class AlpacaBrokerAdapter(BrokerAdapter):
    """Alpaca broker adapter for validator-approved paper execution."""

    def execute_trading_action(
        self,
        *,
        symbol: str,
        current_position: str,
        signal: str,
        dollar_amount: float,
        allow_shorts: bool = False,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "symbol": symbol,
                "current_position": current_position,
                "signal": signal,
                "dollar_amount": dollar_amount,
                "allow_shorts": allow_shorts,
                "message": "Alpaca dry-run accepted; no broker order submitted.",
            }
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        return AlpacaUtils.execute_trading_action(
            symbol=symbol,
            current_position=current_position,
            signal=signal,
            dollar_amount=dollar_amount,
            allow_shorts=allow_shorts,
        )

    def get_account_snapshot(self) -> dict[str, Any]:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        return AlpacaUtils.get_account_info()

    def get_current_position(self, symbol: str) -> str:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        return AlpacaUtils.get_current_position_state(symbol)

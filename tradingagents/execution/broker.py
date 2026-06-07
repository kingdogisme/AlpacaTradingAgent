from __future__ import annotations

from typing import Any, Protocol


class BrokerAdapter(Protocol):
    """Broker side-effect boundary for V2 execution services."""

    def execute_trading_action(
        self,
        *,
        symbol: str,
        current_position: str,
        signal: str,
        dollar_amount: float,
        allow_shorts: bool = False,
    ) -> dict[str, Any]:
        ...

from __future__ import annotations

from typing import Any

from tradingagents.contracts import PortfolioContext, PositionSnapshot


def build_portfolio_context(
    symbol: str,
    *,
    config: dict[str, Any] | None = None,
    account_snapshot: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    current_symbol_position: str | None = None,
    active_plan_reviews: list[Any] | None = None,
) -> PortfolioContext:
    """Build a PortfolioContext from explicit or Alpaca-derived data.

    Passing explicit account/position data keeps the service testable and avoids
    hidden broker dependencies. If values are omitted and credentials are
    available, the helper falls back to current Alpaca account snapshots.
    """

    positions_data = positions
    account_data = account_snapshot
    symbol_position = current_symbol_position
    if positions_data is None or account_data is None or symbol_position is None:
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils

            if positions_data is None:
                positions_data = AlpacaUtils.get_positions_data()
            if account_data is None:
                account_data = AlpacaUtils.get_account_info()
            if symbol_position is None:
                symbol_position = AlpacaUtils.get_current_position_state(symbol)
        except Exception:
            positions_data = positions_data or []
            account_data = account_data or {}
            symbol_position = symbol_position or "NEUTRAL"

    return PortfolioContext(
        account_snapshot=account_data or {},
        current_positions=[_position_snapshot(row) for row in (positions_data or [])],
        current_symbol_position=_normalize_position(symbol_position),
        theme_exposures={},
        policy_config=config or {},
        active_plan_reviews=active_plan_reviews or [],
    )


def _position_snapshot(row: dict[str, Any]) -> PositionSnapshot:
    symbol = str(row.get("Symbol") or row.get("symbol") or "").upper()
    qty = _floatish(row.get("Qty") or row.get("qty"))
    side = "NEUTRAL"
    if qty is not None and qty > 0:
        side = "LONG"
    elif qty is not None and qty < 0:
        side = "SHORT"
    return PositionSnapshot(
        symbol=symbol,
        side=side,
        quantity=qty,
        market_value=_floatish(row.get("Market Value") or row.get("market_value")),
        avg_entry_price=_floatish(row.get("Avg Entry") or row.get("avg_entry_price")),
        unrealized_pl=_floatish(row.get("Total P/L ($)") or row.get("unrealized_pl")),
        raw=row,
    )


def _normalize_position(value: Any) -> str:
    text = str(value or "NEUTRAL").upper()
    return text if text in {"LONG", "SHORT", "NEUTRAL"} else "NEUTRAL"


def _floatish(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None

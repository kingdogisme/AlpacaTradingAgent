from __future__ import annotations

import uuid
from typing import Any

from tradingagents.integrations.robinhood_mcp import (
    DEFAULT_MCP_URL,
    RobinhoodMCPClient,
    default_token_path,
)

from .broker import BrokerAdapter


class RobinhoodBrokerAdapter(BrokerAdapter):
    """Robinhood MCP broker adapter for validator-approved execution."""

    def __init__(
        self,
        *,
        token_path: str | None = None,
        mcp_url: str = DEFAULT_MCP_URL,
        account_number: str | None = None,
        dry_run: bool = True,
        live_orders_enabled: bool = False,
        timeout_seconds: float = 20.0,
    ):
        self.token_path = token_path or str(default_token_path())
        self.mcp_url = mcp_url
        self.account_number = account_number
        self.dry_run = dry_run
        self.live_orders_enabled = live_orders_enabled
        self.timeout_seconds = timeout_seconds

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
        client = RobinhoodMCPClient(
            mcp_url=self.mcp_url,
            token_path=self.token_path,
            timeout_seconds=self.timeout_seconds,
        )
        account = self._resolve_account(client)
        if account is None:
            return {
                "success": False,
                "error": "no active Robinhood agentic account was available",
                "broker": "robinhood",
            }

        request_dry_run = self.dry_run if dry_run is None else bool(dry_run)
        side = _side_from_signal(signal, current_position, allow_shorts=allow_shorts)
        if side is None:
            return {
                "success": True,
                "broker": "robinhood",
                "actions": [{"action": "hold", "message": f"No Robinhood order needed for {symbol}"}],
            }

        order_args = {
            "account_number": account["account_number"],
            "symbol": symbol.upper(),
            "side": side,
            "type": "market",
            "dollar_amount": _format_dollar_amount(dollar_amount),
            "market_hours": "regular_hours",
            "ref_id": str(uuid.uuid4()),
        }
        review = client.review_equity_order({k: v for k, v in order_args.items() if k != "ref_id"})
        if request_dry_run:
            return {
                "success": True,
                "broker": "robinhood",
                "dry_run": True,
                "review": review,
                "order_request": _redact_account(order_args),
            }
        if not self.live_orders_enabled:
            return {
                "success": False,
                "broker": "robinhood",
                "dry_run": False,
                "review": review,
                "order_request": _redact_account(order_args),
                "error": "Robinhood live order submission is disabled; set ROBINHOOD_MCP_LIVE_ORDERS_ENABLED=true to allow --submit-order.",
            }
        placed = client.place_equity_order(order_args)
        return {
            "success": True,
            "broker": "robinhood",
            "dry_run": False,
            "review": review,
            "order": placed,
            "order_request": _redact_account(order_args),
        }

    def get_account_snapshot(self) -> dict[str, Any]:
        client = RobinhoodMCPClient(
            mcp_url=self.mcp_url,
            token_path=self.token_path,
            timeout_seconds=self.timeout_seconds,
        )
        account = self._resolve_account(client)
        if account is None:
            return {}
        portfolio = client.get_portfolio(str(account["account_number"]))
        return _portfolio_to_account_snapshot(portfolio)

    def get_current_position(self, symbol: str) -> str:
        client = RobinhoodMCPClient(
            mcp_url=self.mcp_url,
            token_path=self.token_path,
            timeout_seconds=self.timeout_seconds,
        )
        account = self._resolve_account(client)
        if account is None:
            return "NEUTRAL"
        positions = client.get_equity_positions(str(account["account_number"]))
        symbol_key = symbol.upper()
        for position in positions:
            if str(position.get("symbol") or "").upper() != symbol_key:
                continue
            qty = _safe_float(position.get("quantity") or position.get("qty"))
            if qty and qty > 0:
                return "LONG"
            if qty and qty < 0:
                return "SHORT"
        return "NEUTRAL"

    def _resolve_account(self, client: RobinhoodMCPClient) -> dict[str, Any] | None:
        accounts = client.get_accounts()
        if self.account_number:
            for account in accounts:
                if account.get("account_number") == self.account_number:
                    return account
            return None
        active = [account for account in accounts if account.get("state") == "active"]
        agentic = [account for account in active if account.get("agentic_allowed") is True]
        if agentic:
            return sorted(agentic, key=lambda item: (not bool(item.get("is_default")), str(item.get("account_number"))))[0]
        return None


def _side_from_signal(signal: str, current_position: str, *, allow_shorts: bool) -> str | None:
    normalized_signal = str(signal or "").upper()
    position = str(current_position or "NEUTRAL").upper()
    if allow_shorts:
        if normalized_signal == "LONG" and position != "LONG":
            return "buy"
        if normalized_signal == "SHORT" and position != "SHORT":
            return "sell"
        return None
    if normalized_signal == "BUY" and position != "LONG":
        return "buy"
    if normalized_signal == "SELL" and position == "LONG":
        return "sell"
    return None


def _redact_account(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    account_number = str(redacted.get("account_number") or "")
    if account_number:
        redacted["account_number"] = "****" + account_number[-4:]
    return redacted


def _format_dollar_amount(value: Any) -> str:
    amount = float(value)
    if amount <= 0:
        raise ValueError("Robinhood dollar_amount must be positive")
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _portfolio_to_account_snapshot(portfolio: dict[str, Any]) -> dict[str, Any]:
    buying_power = portfolio.get("buying_power") if isinstance(portfolio.get("buying_power"), dict) else {}
    equity = _safe_float(portfolio.get("total_value"))
    cash = _safe_float(portfolio.get("cash"))
    bp = _safe_float(buying_power.get("buying_power")) if isinstance(buying_power, dict) else None
    return {
        "equity": equity or 0,
        "buying_power": bp if bp is not None else 0,
        "cash": cash if cash is not None else 0,
        "currency": portfolio.get("currency")
        or (buying_power.get("display_currency") if isinstance(buying_power, dict) else "USD"),
        "broker": "robinhood",
    }


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

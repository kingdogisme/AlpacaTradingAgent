from __future__ import annotations

from dataclasses import dataclass, field
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
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass
class BrokerRouter(BrokerAdapter):
    """Select a broker adapter at order time without coupling upstream layers."""

    config: dict[str, Any] | None = None
    adapters: dict[str, BrokerAdapter] = field(default_factory=dict)

    def execute_trading_action(
        self,
        *,
        symbol: str,
        current_position: str,
        signal: str,
        dollar_amount: float,
        allow_shorts: bool = False,
        dry_run: bool | None = None,
        broker_name: str | None = None,
    ) -> dict[str, Any]:
        selected = self.resolve_broker_name(symbol=symbol, requested=broker_name)
        adapter = self.adapter(selected)
        response = adapter.execute_trading_action(
            symbol=symbol,
            current_position=current_position,
            signal=signal,
            dollar_amount=dollar_amount,
            allow_shorts=allow_shorts,
            dry_run=dry_run,
        )
        return {"broker_name": selected, **response}

    def resolve_broker_name(self, *, symbol: str, requested: str | None = None) -> str:
        if requested:
            return _normalize_broker_name(requested)
        cfg = self.config or {}
        routes = cfg.get("broker_routes") if isinstance(cfg.get("broker_routes"), dict) else {}
        symbol_routes = routes.get("symbols") if isinstance(routes.get("symbols"), dict) else {}
        symbol_key = str(symbol or "").upper()
        if symbol_key in symbol_routes:
            return _normalize_broker_name(symbol_routes[symbol_key])
        default = routes.get("default") or cfg.get("broker_adapter") or cfg.get("execution_broker") or "alpaca"
        return _normalize_broker_name(default)

    def adapter(self, broker_name: str) -> BrokerAdapter:
        normalized = _normalize_broker_name(broker_name)
        if normalized not in self.adapters:
            adapter = create_broker_adapter(self.config, broker_name=normalized)
            if adapter is None:
                raise ValueError(f"broker adapter is disabled: {normalized}")
            self.adapters[normalized] = adapter
        return self.adapters[normalized]

    def get_account_snapshot(self, *, broker_name: str | None = None, symbol: str = "") -> dict[str, Any]:
        selected = self.resolve_broker_name(symbol=symbol, requested=broker_name)
        adapter = self.adapter(selected)
        getter = getattr(adapter, "get_account_snapshot", None)
        if not callable(getter):
            return {}
        snapshot = getter()
        return snapshot if isinstance(snapshot, dict) else {}

    def get_current_position(self, symbol: str, *, broker_name: str | None = None) -> str:
        selected = self.resolve_broker_name(symbol=symbol, requested=broker_name)
        adapter = self.adapter(selected)
        getter = getattr(adapter, "get_current_position", None)
        if not callable(getter):
            return "NEUTRAL"
        return str(getter(symbol) or "NEUTRAL").upper()


def create_broker_router(config: dict[str, Any] | None = None) -> BrokerRouter:
    return BrokerRouter(config=config or {})


def create_broker_adapter(
    config: dict[str, Any] | None = None,
    *,
    broker_name: str | None = None,
) -> BrokerAdapter | None:
    """Create the configured broker adapter for execution services."""
    cfg = config or {}
    selected = _normalize_broker_name(broker_name or cfg.get("broker_adapter") or cfg.get("execution_broker") or "alpaca")
    if selected in {"", "none", "disabled"}:
        return None
    if selected == "alpaca":
        from .alpaca_broker import AlpacaBrokerAdapter

        return AlpacaBrokerAdapter()
    if selected == "robinhood":
        from .robinhood_broker import RobinhoodBrokerAdapter

        return RobinhoodBrokerAdapter(
            token_path=cfg.get("robinhood_mcp_token_path"),
            mcp_url=str(cfg.get("robinhood_mcp_url") or "https://agent.robinhood.com/mcp/trading"),
            account_number=cfg.get("robinhood_account_number"),
            dry_run=bool(cfg.get("robinhood_mcp_dry_run", True)),
            live_orders_enabled=bool(cfg.get("robinhood_mcp_live_orders_enabled", False)),
            timeout_seconds=float(cfg.get("robinhood_mcp_timeout_seconds") or 20),
        )
    raise ValueError(f"unsupported broker adapter: {selected}")


def _normalize_broker_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")

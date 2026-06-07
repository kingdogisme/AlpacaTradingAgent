from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradingagents.execution import ExecutionService
from tradingagents.trade_lifecycle.models import ConditionalTradePlan, MarketObservation


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def _plan():
    return ConditionalTradePlan(
        symbol="NVDA",
        action="BUY",
        trigger={"type": "market"},
        invalidation={"price_below": 900.0},
        valid_until=_future(),
        max_notional=500.0,
        risk_budget={"max_notional": 500.0, "max_gap_pct": 0.08},
        execution_policy={"notional": 500.0, "paper_only": True},
    )


def _observation(price=1000.0):
    return MarketObservation(symbol="NVDA", price=price, gap_pct=0.01)


def test_execution_validate_returns_needs_review_without_broker_call():
    result = ExecutionService(config={"alpaca_use_paper": True}).validate(
        _plan(),
        _observation(),
        account_snapshot={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )

    assert result.status == "needs_review"
    assert result.validation_passed is True
    assert result.broker_response is None
    assert result.order_request["notional"] == 500.0


def test_execution_execute_uses_injected_broker_only_after_validation():
    calls = []

    class FakeBroker:
        def execute_trading_action(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "order_id": "ord_1"}

    result = ExecutionService(config={"alpaca_use_paper": True}, broker=FakeBroker()).execute(
        _plan(),
        _observation(),
        account_snapshot={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )

    assert result.status == "executed"
    assert result.broker_response["order_id"] == "ord_1"
    assert calls[0]["symbol"] == "NVDA"


def test_execution_rejects_without_broker_call_when_validation_fails():
    calls = []

    class FakeBroker:
        def execute_trading_action(self, **kwargs):
            calls.append(kwargs)
            return {"success": True}

    result = ExecutionService(config={"alpaca_use_paper": False}, broker=FakeBroker()).execute(
        _plan(),
        _observation(),
        account_snapshot={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )

    assert result.status == "rejected"
    assert "live_account" in result.reason_codes
    assert calls == []


def test_execution_dry_run_broker_stays_in_review_status():
    class DryRunBroker:
        def execute_trading_action(self, **_kwargs):
            return {"success": True, "dry_run": True, "review": {"estimated_total": "500.00"}}

    result = ExecutionService(config={"alpaca_use_paper": True}, broker=DryRunBroker()).execute(
        _plan(),
        _observation(),
        account_snapshot={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )

    assert result.status == "needs_review"
    assert result.validation_passed is True
    assert "broker_dry_run" in result.reason_codes
    assert result.broker_response["review"]["estimated_total"] == "500.00"


def test_execution_can_use_router_owned_snapshot_and_position():
    calls = []

    class FakeRouter:
        def get_account_snapshot(self, **kwargs):
            calls.append(("snapshot", kwargs))
            return {"equity": 10000, "buying_power": 10000}

        def get_current_position(self, symbol, **kwargs):
            calls.append(("position", symbol, kwargs))
            return "NEUTRAL"

        def resolve_broker_name(self, **_kwargs):
            return "robinhood"

        def execute_trading_action(self, **kwargs):
            calls.append(("execute", kwargs))
            return {"success": True, "dry_run": True, "broker": "robinhood"}

    result = ExecutionService(config={"alpaca_use_paper": True}, broker=FakeRouter()).execute(
        _plan(),
        _observation(),
        broker_name="robinhood",
        dry_run=True,
    )

    assert result.status == "needs_review"
    assert result.account_snapshot["buying_power"] == 10000
    assert calls[0] == ("snapshot", {"broker_name": "robinhood", "symbol": "NVDA"})
    assert calls[-1][1]["broker_name"] == "robinhood"
    assert calls[-1][1]["dry_run"] is True

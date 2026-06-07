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

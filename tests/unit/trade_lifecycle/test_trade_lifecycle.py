from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tradingagents.trade_lifecycle import (
    ConditionalTradePlan,
    MarketObservation,
    PreTradeValidator,
    TradeMonitorService,
    TradePlanRepository,
    TradePlanStatus,
    TradeTrigger,
    persist_approved_plan,
)


def _future(days: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _plan(**overrides):
    payload = {
        "symbol": "AAPL",
        "action": "BUY",
        "trigger": {"type": "market"},
        "invalidation": {"price_below": 95.0},
        "valid_until": _future(),
        "max_notional": 500.0,
        "risk_budget": {"max_notional": 500.0, "max_gap_pct": 0.08, "min_volume_ratio": 0.2},
        "execution_policy": {"notional": 500.0, "paper_only": True},
    }
    payload.update(overrides)
    return ConditionalTradePlan(**payload)


def _observation(**overrides):
    payload = {
        "symbol": "AAPL",
        "price": 100.0,
        "prev_close": 99.0,
        "gap_pct": 0.01,
        "volume_ratio": 1.0,
    }
    payload.update(overrides)
    return MarketObservation(**payload)


def test_conditional_trade_plan_requires_valid_until_and_validates_transitions():
    with pytest.raises(Exception):
        ConditionalTradePlan(symbol="AAPL", action="BUY", trigger=TradeTrigger(type="market"))

    plan = _plan()
    triggered = plan.transition_to(TradePlanStatus.TRIGGERED)
    assert triggered.status == TradePlanStatus.TRIGGERED
    with pytest.raises(ValueError):
        triggered.transition_to(TradePlanStatus.ACTIVE)


def test_repository_upsert_list_expire_and_events(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan(valid_until=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    repo.upsert_plan(plan)
    assert repo.get_plan(plan.plan_id).symbol == "AAPL"
    assert len(repo.list_active_plans(["AAPL"])) == 1

    expired = repo.expire_stale_plans()
    assert [item.plan_id for item in expired] == [plan.plan_id]
    assert repo.get_plan(plan.plan_id).status == TradePlanStatus.EXPIRED
    assert any(event["event_type"] == "status_change" for event in repo.list_events(plan.plan_id))


def test_validator_rejects_expired_invalidation_live_gap_and_liquidity():
    validator = PreTradeValidator({"alpaca_use_paper": False})
    result = validator.validate(_plan(), _observation())
    assert not result.passed
    assert any("live account" in reason for reason in result.reasons)

    validator = PreTradeValidator({"alpaca_use_paper": True})
    result = validator.validate(_plan(), _observation(price=94.0))
    assert not result.passed
    assert any("invalidation" in reason for reason in result.reasons)

    result = validator.validate(_plan(), _observation(gap_pct=0.12))
    assert not result.passed
    assert any("gap" in reason for reason in result.reasons)

    result = validator.validate(_plan(), _observation(volume_ratio=0.1))
    assert not result.passed
    assert any("volume_ratio" in reason for reason in result.reasons)


def test_validator_approves_and_builds_execution_policy():
    result = PreTradeValidator({"alpaca_use_paper": True}).validate(_plan(), _observation())
    assert result.passed
    assert result.execution_policy.notional == 500
    assert result.execution_policy.paper_only is True


def test_hold_plan_does_not_create_order():
    result = PreTradeValidator({"alpaca_use_paper": True}).validate(
        _plan(action="HOLD", invalidation={}),
        _observation(),
    )
    assert not result.passed
    assert result.decision == "no_order"


def test_monitor_once_triggers_validator_and_paper_order(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan()
    repo.upsert_plan(plan)

    service = TradeMonitorService({"alpaca_use_paper": True, "trade_lifecycle_db_path": str(tmp_path / "trade.sqlite")}, repo)

    with patch.object(service, "_observe", return_value=_observation()), patch.object(
        service, "_account_info", return_value={"equity": 10000, "buying_power": 10000}
    ), patch.object(
        service, "_current_position", return_value="NEUTRAL"
    ), patch.object(
        service,
        "_execute_plan",
        return_value={"success": True, "actions": [{"action": "buy"}]},
    ) as execute:
        result = service.run_once(symbols=["AAPL"])

    assert result["processed"][0]["order_result"]["success"] is True
    assert repo.get_plan(plan.plan_id).status == TradePlanStatus.EXECUTED
    execute.assert_called_once()


def test_monitor_does_not_execute_untriggered_plan(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    repo.upsert_plan(_plan(trigger={"type": "price_above", "price_above": 110.0}))
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)

    with patch.object(service, "_observe", return_value=_observation(price=100.0)), patch.object(
        service,
        "_execute_plan",
    ) as execute:
        result = service.run_once(symbols=["AAPL"])

    assert result["processed"][0]["decision"] == "waiting"
    execute.assert_not_called()


def test_monitor_debounce_requires_consecutive_observations(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan(trigger={"type": "market", "debounce_observations": 2})
    repo.upsert_plan(plan)
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)

    with patch.object(service, "_observe", return_value=_observation()), patch.object(
        service, "_account_info", return_value={"equity": 10000, "buying_power": 10000}
    ), patch.object(service, "_current_position", return_value="NEUTRAL"), patch.object(
        service, "_execute_plan", return_value={"success": True, "actions": [{"action": "buy"}]}
    ) as execute:
        first = service.run_once(symbols=["AAPL"])
        second = service.run_once(symbols=["AAPL"])

    assert first["processed"][0]["decision"] == "waiting"
    assert second["processed"][0]["order_result"]["success"] is True
    execute.assert_called_once()


def test_persist_approved_plan_keeps_existing_on_conflicting_signal_without_major_news(tmp_path):
    config = {
        "trade_lifecycle_db_path": str(tmp_path / "trade.sqlite"),
        "trade_lifecycle_default_notional": 500,
    }
    first_state = {
        "company_of_interest": "AAPL",
        "trading_mode": "investment",
        "trading_horizon": "swing",
        "final_trade_decision": "Approved. Invalidation at 95.\nFINAL TRANSACTION PROPOSAL: **BUY**",
    }
    second_state = {
        **first_state,
        "final_trade_decision": "Approved. Invalidation at 105.\nFINAL TRANSACTION PROPOSAL: **SELL**",
    }

    first = persist_approved_plan(first_state, config=config, source_run_id="run-1")
    second = persist_approved_plan(second_state, config=config, source_run_id="run-2")

    assert first.plan_id == second.plan_id
    assert second.source_run_id == "run-1"
    events = TradePlanRepository(config["trade_lifecycle_db_path"]).list_events(first.plan_id)
    assert any(event["event_type"] == "signal_reconciliation_conflict" for event in events)

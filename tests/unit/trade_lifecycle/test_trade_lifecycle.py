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
    build_plan_from_final_state,
    evaluate_trigger,
    monitor_status,
    monitor_preflight,
    plan_health,
    persist_approved_plan,
    reconcile_plans,
    review_active_plan,
    summarize_plan,
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


def test_monitor_once_requests_review_without_paper_order(tmp_path):
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

    assert result["processed"][0]["decision"] == "needs_review"
    assert repo.get_plan(plan.plan_id).status == TradePlanStatus.NEEDS_REVIEW
    execute.assert_not_called()
    events = repo.list_events(plan.plan_id)
    assert any(event["event_type"] == "trigger_review_required" for event in events)


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


def test_monitor_respects_regular_market_hours_and_writes_heartbeat(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan()
    repo.upsert_plan(plan)
    service = TradeMonitorService({"alpaca_use_paper": True, "trade_monitor_use_alpaca_clock": False}, repo)

    with patch("tradingagents.trade_lifecycle.monitor.datetime") as dt:
        dt.now.return_value = datetime(2026, 6, 7, 15, 0, tzinfo=timezone.utc)
        dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        result = service.run_once(respect_market_hours=True)

    assert result["skipped"] is True
    assert result["skip_reason"] == "outside_regular_market_hours"
    assert result["processed"] == []
    assert any(event["event_type"] == "monitor_heartbeat" for event in repo.list_monitor_events())


def test_monitor_market_hours_prefers_alpaca_clock_and_falls_back(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    service = TradeMonitorService({"trade_monitor_use_alpaca_clock": True}, repo)
    fallback = service._market_session_state(datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc))
    assert fallback["session_source"] == "local_time_fallback"
    assert fallback["is_regular_session"] is False

    class _Clock:
        is_open = True
        timestamp = datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc)
        next_open = datetime(2026, 6, 8, 13, 30, tzinfo=timezone.utc)
        next_close = datetime(2026, 6, 8, 20, 0, tzinfo=timezone.utc)

    with patch("tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client") as client:
        client.return_value.get_clock.return_value = _Clock()
        state = service._market_session_state(datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc))

    assert state["session_source"] == "alpaca_clock"
    assert state["is_regular_session"] is True
    assert state["next_open"] is not None


def test_monitor_status_lists_candidates_and_latest_heartbeat(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    repo.upsert_plan(_plan(symbol="IREN"))
    repo.upsert_plan(_plan(symbol="MSFT", action="HOLD"))
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)
    service.run_once(respect_market_hours=True)

    status = monitor_status(repo)

    assert status["candidate_count"] == 1
    assert status["candidates"][0]["symbol"] == "IREN"
    assert status["open_plan_count"] == 2
    assert status["monitor_running"] is False
    assert status["monitor_state"] == "recent_heartbeat_no_running_lock"
    assert status["heartbeat_stale"] is False
    assert status["monitor_running_evidence"]["event_type"] == "monitor_heartbeat"

    import fcntl

    lock_path = tmp_path / "monitor.lock"
    with lock_path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked_status = monitor_status(repo, lock_path=lock_path)
        assert locked_status["monitor_running"] is True
        assert locked_status["monitor_state"] == "running"
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def test_monitor_run_forever_can_exit_after_max_iterations(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)

    with patch.object(service, "run_once", return_value={"processed": []}) as run_once, patch(
        "tradingagents.trade_lifecycle.monitor.time.sleep"
    ) as sleep:
        service.run_forever(interval_seconds=1, max_iterations=2)

    assert run_once.call_count == 2
    assert sleep.call_count == 1


def test_monitor_sends_optional_review_webhook_without_order_execution(tmp_path):
    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan(symbol="IREN")
    repo.upsert_plan(plan)
    service = TradeMonitorService(
        {
            "alpaca_use_paper": True,
            "trade_monitor_review_webhook_url": "https://example.test/review",
        },
        repo,
    )

    with patch.object(service, "_observe", return_value=_observation(symbol="IREN")), patch.object(
        service, "_execute_plan"
    ) as execute, patch("tradingagents.trade_lifecycle.monitor.request.urlopen", return_value=_Response()) as urlopen:
        result = service.run_once(symbols=["IREN"])

    assert result["processed"][0]["decision"] == "needs_review"
    execute.assert_not_called()
    assert urlopen.called
    notification = repo.latest_monitor_event("trigger_review_notification")
    assert notification["status"] == "ok"
    assert notification["payload"]["plan_id"] == plan.plan_id


def test_monitor_sends_optional_review_im_without_order_execution(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan(
        symbol="IREN",
        trigger={"type": "price_above", "price_above": 10.0, "volume_min_ratio": 1.0},
    )
    repo.upsert_plan(plan)
    service = TradeMonitorService(
        {
            "alpaca_use_paper": True,
            "trade_monitor_review_im_channel": "openclaw-weixin",
            "trade_monitor_review_im_account": "weixin-account",
            "trade_monitor_review_im_target": "user@im.wechat",
            "trade_monitor_openclaw_bin": "openclaw",
        },
        repo,
    )

    completed = type(
        "Completed",
        (),
        {
            "returncode": 0,
            "stdout": '{"payload":{"result":{"messageId":"msg-1"}}}',
            "stderr": "",
        },
    )()
    with patch.object(service, "_observe", return_value=_observation(symbol="IREN", price=12.0)), patch.object(
        service, "_execute_plan"
    ) as execute, patch("tradingagents.trade_lifecycle.monitor.subprocess.run", return_value=completed) as run:
        result = service.run_once(symbols=["IREN"])

    assert result["processed"][0]["decision"] == "needs_review"
    execute.assert_not_called()
    cmd = run.call_args.args[0]
    assert cmd[:5] == ["openclaw", "message", "send", "--channel", "openclaw-weixin"]
    assert "--target" in cmd
    assert cmd[cmd.index("--target") + 1] == "user@im.wechat"
    assert "--account" in cmd
    assert cmd[cmd.index("--account") + 1] == "weixin-account"
    assert "Required review: execute / resize / cancel / supersede" in cmd[cmd.index("--message") + 1]
    notification = repo.latest_monitor_event("trigger_review_im_notification")
    assert notification["status"] == "ok"
    assert notification["payload"]["result"]["payload"]["result"]["messageId"] == "msg-1"


def test_monitor_preflight_reports_missing_infrastructure(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_CHANNEL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_TARGET", raising=False)
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    repo.upsert_plan(_plan(symbol="IREN"))

    result = monitor_preflight(repo, config={})

    assert result["ready"] is False
    assert "alpaca_credentials_ready" in result["blocking"]
    assert result["checks"]["has_monitorable_candidates"] is True
    assert result["warnings"] == ["review_notification_not_configured"]


def test_monitor_preflight_accepts_review_im_notification(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_WEBHOOK_URL", raising=False)
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    repo.upsert_plan(_plan(symbol="IREN"))

    result = monitor_preflight(
        repo,
        config={
            "trade_monitor_review_im_channel": "openclaw-weixin",
            "trade_monitor_review_im_target": "user@im.wechat",
        },
    )

    assert result["checks"]["review_im_configured"] is True
    assert result["checks"]["review_notification_configured"] is True
    assert result["warnings"] == []


def test_plan_review_marks_breakout_trigger_met_or_partial():
    plan = _plan(
        symbol="NBIS",
        source_run_id="2026-05-30-run",
        trigger={"type": "price_above", "price_above": 240.0, "volume_min_ratio": 1.0},
        invalidation={"price_below": 209.99},
        horizon="position",
    )

    partial = review_active_plan(plan, _observation(symbol="NBIS", price=264.49, volume_ratio=0.82))
    met = review_active_plan(plan, _observation(symbol="NBIS", price=264.49, volume_ratio=1.15))

    assert partial.status.value == "partially_met"
    assert partial.required_action == "review"
    assert partial.allowed_decisions == ["execute", "resize", "cancel", "supersede"]
    assert met.status.value == "met"


def test_trigger_met_plan_is_not_silently_replaced_without_supersede_reason(tmp_path):
    config = {"trade_lifecycle_db_path": str(tmp_path / "trade.sqlite")}
    repo = TradePlanRepository(config["trade_lifecycle_db_path"])
    existing = _plan(
        symbol="NBIS",
        source_run_id="run-20260530",
        trigger={"type": "price_above", "price_above": 240.0},
        invalidation={"price_below": 209.99},
        horizon="position",
    )
    repo.upsert_plan(existing)
    state = {
        "company_of_interest": "NBIS",
        "trading_mode": "investment",
        "trading_horizon": "position",
        "active_plan_review": {
            "reviews": [
                review_active_plan(existing, _observation(symbol="NBIS", price=264.49)).model_dump(mode="json")
            ]
        },
        "final_trade_decision": "Wait for a new pullback to 241 before buying. Entry at 241. Invalidation at 226.\nFINAL TRANSACTION PROPOSAL: **BUY**",
    }

    result = persist_approved_plan(state, config=config, source_run_id="run-20260601")

    assert result.plan_id == existing.plan_id
    assert repo.get_plan(existing.plan_id).trigger.price_above == 240.0
    events = repo.list_events(existing.plan_id)
    assert any(event["event_type"] == "trigger_review_required" for event in events)


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
    assert second["processed"][0]["decision"] == "needs_review"
    assert repo.get_plan(plan.plan_id).status == TradePlanStatus.NEEDS_REVIEW
    execute.assert_not_called()


def test_monitor_debounce_resets_after_untriggered_observation(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    plan = _plan(trigger={"type": "price_above", "price_above": 101.0, "debounce_observations": 2})
    repo.upsert_plan(plan)
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)

    observations = [_observation(price=102.0), _observation(price=100.0), _observation(price=102.0), _observation(price=102.0)]
    with patch.object(service, "_observe", side_effect=observations), patch.object(
        service, "_account_info", return_value={"equity": 10000, "buying_power": 10000}
    ), patch.object(service, "_current_position", return_value="NEUTRAL"), patch.object(
        service, "_execute_plan", return_value={"success": True, "actions": [{"action": "buy"}]}
    ) as execute:
        first = service.run_once(symbols=["AAPL"])
        second = service.run_once(symbols=["AAPL"])
        third = service.run_once(symbols=["AAPL"])
        fourth = service.run_once(symbols=["AAPL"])

    assert first["processed"][0]["decision"] == "waiting"
    assert second["processed"][0]["decision"] == "waiting"
    assert third["processed"][0]["decision"] == "waiting"
    assert fourth["processed"][0]["decision"] == "needs_review"
    assert repo.get_plan(plan.plan_id).status == TradePlanStatus.NEEDS_REVIEW
    execute.assert_not_called()


def test_persist_approved_plan_keeps_existing_on_conflicting_signal_without_major_news(tmp_path):
    config = {
        "trade_lifecycle_db_path": str(tmp_path / "trade.sqlite"),
        "trade_lifecycle_default_notional": 500,
    }
    first_state = {
        "company_of_interest": "AAPL",
        "trading_mode": "investment",
        "trading_horizon": "swing",
        "final_trade_decision": "Approved. Entry at 100. Invalidation at 95.\nFINAL TRANSACTION PROPOSAL: **BUY**",
    }
    second_state = {
        **first_state,
        "final_trade_decision": "Approved. Entry at 99. Invalidation at 105.\nFINAL TRANSACTION PROPOSAL: **SELL**",
    }

    first = persist_approved_plan(first_state, config=config, source_run_id="run-1")
    second = persist_approved_plan(second_state, config=config, source_run_id="run-2")

    assert first.plan_id == second.plan_id
    assert second.source_run_id == "run-1"
    events = TradePlanRepository(config["trade_lifecycle_db_path"]).list_events(first.plan_id)
    assert any(event["event_type"] == "signal_reconciliation_conflict" for event in events)


def test_structured_plan_is_canonical_and_text_fallback_supports_chinese():
    valid_until = _future()
    structured_state = {
        "company_of_interest": "AAPL",
        "trading_mode": "investment",
        "trading_horizon": "swing",
        "final_trade_decision": "文本里没有可解析价格\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "conditional_trade_plan": {
            "symbol": "AAPL",
            "action": "BUY",
            "trigger": {"type": "price_above", "price_above": 101.0},
            "invalidation": {"price_below": 95.0},
            "valid_until": valid_until,
            "max_notional": 750.0,
            "risk_budget": {"max_notional": 750.0},
        },
    }
    plan = build_plan_from_final_state(structured_state, config={"alpaca_use_paper": True})
    assert plan.trigger.type == "price_above"
    assert plan.trigger.price_above == 101.0
    assert plan.invalidation.price_below == 95.0
    assert plan.metadata["builder"] == "structured_v1"

    zh_state = {
        "company_of_interest": "AAPL",
        "trading_mode": "investment",
        "trading_horizon": "swing",
        "final_trade_decision": "入场 102；止损/失效 96；仓位规模 $600。\nFINAL TRANSACTION PROPOSAL: **BUY**",
    }
    zh_plan = build_plan_from_final_state(zh_state, config={})
    assert zh_plan.trigger.price_above == 102.0
    assert zh_plan.invalidation.price_below == 96.0
    assert zh_plan.max_notional == 600.0


def test_structured_or_trigger_plan_stays_active_for_strong_trend_waitlist():
    state = {
        "company_of_interest": "IREN",
        "trading_mode": "investment",
        "trading_horizon": "position",
        "final_trade_decision": "HOLD now, buy on trigger.\nFINAL TRANSACTION PROPOSAL: **HOLD**",
        "conditional_trade_plan": {
            "symbol": "IREN",
            "action": "BUY",
            "trigger": {
                "type": "OR",
                "conditions": [
                    {
                        "price_close_above": 69.0,
                        "volume": "above_average",
                        "confirmation": "next_day_or_retest_holds_67_69",
                    },
                    {
                        "pullback_zone_low": 60.0,
                        "pullback_zone_high": 62.0,
                        "volume": "above_average",
                        "confirmation": "holds_above_60.39_and_bullish_volume_reversal_reclaims_short_MAs",
                    },
                ],
            },
            "invalidation": 60.39,
            "valid_until": "2026-09-02",
            "risk_budget": {"risk_budget_pct": 0.01, "max_notional_pct": 0.1},
        },
    }

    plan = build_plan_from_final_state(state, config={})

    assert plan.status == TradePlanStatus.ACTIVE
    assert plan.action.value == "BUY"
    assert len(plan.trigger.conditions) == 2
    assert plan.trigger.conditions[0].type == "price_above"
    assert plan.trigger.conditions[0].price_above == 69.0
    assert plan.trigger.conditions[0].volume_min_ratio == 1.0
    assert plan.trigger.conditions[1].type == "price_between"
    assert plan.trigger.conditions[1].price_low == 60.0
    assert plan.trigger.conditions[1].price_high == 62.0
    assert plan.trigger.conditions[1].require_reclaim_sma_50 is True
    assert plan.invalidation.price_below == 60.39


def test_multiline_conditional_plan_json_is_extracted():
    state = {
        "company_of_interest": "IREN",
        "trading_mode": "investment",
        "trading_horizon": "position",
        "final_trade_decision": """conditional_trade_plan_json: {
          "symbol": "IREN",
          "action": "BUY",
          "trigger": {
            "type": "OR",
            "conditions": [
              {"price_close_above": 69.0, "volume": "above_average"},
              {"pullback_zone_low": 60.0, "pullback_zone_high": 62.0}
            ]
          },
          "invalidation": 60.39,
          "valid_until": "2026-09-02"
        }

FINAL TRANSACTION PROPOSAL: **HOLD**""",
    }

    plan = build_plan_from_final_state(state, config={})

    assert plan.status == TradePlanStatus.ACTIVE
    assert len(plan.trigger.conditions) == 2
    assert plan.invalidation.price_below == 60.39


def test_or_trigger_monitor_breakout_and_pullback_review_only(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    breakout = _plan(
        symbol="IREN",
        trigger={
            "type": "market",
            "conditions": [
                {"type": "price_above", "price_above": 69.0, "volume_min_ratio": 1.0},
                {
                    "type": "price_between",
                    "price_low": 60.0,
                    "price_high": 62.0,
                    "volume_min_ratio": 1.0,
                    "require_reclaim_sma_50": True,
                },
            ],
        },
        invalidation={"price_below": 60.39},
    )
    repo.upsert_plan(breakout)
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)

    with patch.object(service, "_observe", return_value=_observation(symbol="IREN", price=69.5, volume_ratio=1.2)), patch.object(
        service, "_execute_plan"
    ) as execute:
        result = service.run_once(symbols=["IREN"])

    assert result["processed"][0]["decision"] == "needs_review"
    assert result["processed"][0]["trigger_result"]["matched_leg"]["leg_index"] == 0
    assert repo.get_plan(breakout.plan_id).status == TradePlanStatus.NEEDS_REVIEW
    execute.assert_not_called()

    pullback = _plan(
        symbol="IREN",
        trigger=breakout.trigger.model_dump(mode="json"),
        invalidation={"price_below": 60.39},
    )
    repo.upsert_plan(pullback)
    service = TradeMonitorService({"alpaca_use_paper": True}, repo)
    with patch.object(
        service,
        "_observe",
        return_value=_observation(symbol="IREN", price=61.5, volume_ratio=1.1, sma_50=61.0),
    ), patch.object(service, "_execute_plan") as execute:
        result = service.run_once(symbols=["IREN"])

    assert result["processed"][0]["decision"] == "needs_review"
    assert result["processed"][0]["trigger_result"]["matched_leg"]["leg_index"] == 1
    execute.assert_not_called()


def test_or_trigger_partial_when_confirmation_missing():
    plan = _plan(
        symbol="IREN",
        trigger={
            "type": "market",
            "conditions": [
                {"type": "price_above", "price_above": 69.0, "volume_min_ratio": 1.2},
            ],
        },
        invalidation={"price_below": 60.39},
    )

    result = evaluate_trigger(plan, _observation(symbol="IREN", price=69.5, volume_ratio=0.8))
    review = review_active_plan(plan, _observation(symbol="IREN", price=69.5, volume_ratio=0.8))

    assert result["partial"] is True
    assert result["met"] is False
    assert review.status.value == "partially_met"


def test_missing_trigger_or_invalidation_is_not_activated(tmp_path):
    config = {"trade_lifecycle_db_path": str(tmp_path / "trade.sqlite")}
    state = {
        "company_of_interest": "AAPL",
        "trading_mode": "investment",
        "trading_horizon": "swing",
        "final_trade_decision": "Good idea, no numeric controls.\nFINAL TRANSACTION PROPOSAL: **BUY**",
    }
    plan = persist_approved_plan(state, config=config)
    assert plan.status == TradePlanStatus.REJECTED
    assert TradePlanRepository(config["trade_lifecycle_db_path"]).list_active_plans(["AAPL"]) == []


def test_short_plan_uses_price_below_trigger_and_price_above_invalidation():
    state = {
        "company_of_interest": "AAPL",
        "trading_mode": "trading",
        "trading_horizon": "swing",
        "final_trade_decision": "Entry 90. Invalidation 95.\nFINAL TRANSACTION PROPOSAL: **SHORT**",
    }
    plan = build_plan_from_final_state(state, config={"allow_shorts": True})
    assert plan.trigger.type == "price_below"
    assert plan.trigger.price_below == 90.0
    assert plan.invalidation.price_above == 95.0


def test_validator_uses_position_and_stable_reason_codes():
    validator = PreTradeValidator({"alpaca_use_paper": True})
    sell_result = validator.validate(_plan(action="SELL"), _observation(), current_position="NEUTRAL")
    assert sell_result.reason_code == "flat_sell"
    assert sell_result.decision == "no_order"

    buy_result = validator.validate(_plan(action="BUY"), _observation(), current_position="LONG")
    assert buy_result.reason_code == "already_long"
    assert buy_result.decision == "no_order"

    short_result = validator.validate(
        _plan(symbol="BTC/USD", action="SHORT", invalidation={"price_above": 120.0}, execution_policy={"notional": 500, "paper_only": True, "allow_shorts": True}),
        _observation(symbol="BTC/USD"),
        current_position="NEUTRAL",
    )
    assert short_result.reason_code == "crypto_short_forbidden"


def test_validator_sets_idempotency_policy_and_rejects_risk_caps():
    approved = PreTradeValidator({"alpaca_use_paper": True}).validate(
        _plan(),
        _observation(),
        account_info={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )
    assert approved.passed
    assert approved.execution_policy.client_order_id.startswith("ata-")
    assert approved.execution_policy.idempotency_key

    rejected = PreTradeValidator({"alpaca_use_paper": True, "max_single_name_notional_pct": 0.01}).validate(
        _plan(),
        _observation(),
        account_info={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )
    assert rejected.reason_code == "single_name_cap"


def test_plan_reporting_aggregates_latest_event_validation_and_health(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    active = _plan(symbol="AAPL")
    rejected = _plan(symbol="MSFT", status="rejected")
    executed = _plan(symbol="NVDA", status="executed")
    repo.upsert_plan(active)
    repo.upsert_plan(rejected)
    repo.upsert_plan(executed)
    validation = PreTradeValidator({"alpaca_use_paper": True}).validate(
        active,
        _observation(),
        account_info={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )
    repo.record_validation(validation)

    summary = summarize_plan(active, repo)
    health = plan_health(repo)

    assert summary["latest_validation"]["reason_code"] == "approved"
    assert summary["latest_event"]["event_type"] == "validation"
    assert health["counts_by_status"]["active"] == 1
    assert health["counts_by_status"]["rejected"] == 1
    assert health["counts_by_status"]["executed"] == 1
    assert health["counts_by_progress"]["waiting_trigger"] == 1


def test_reconcile_triggered_plan_marks_review_without_order_and_executes_with_order_event(tmp_path):
    repo = TradePlanRepository(tmp_path / "trade.sqlite")
    missing_order = _plan(symbol="AAPL")
    completed_order = _plan(symbol="MSFT")
    repo.upsert_plan(missing_order)
    repo.upsert_plan(completed_order)
    repo.update_status(missing_order.plan_id, TradePlanStatus.TRIGGERED, reason="triggered")
    repo.update_status(completed_order.plan_id, TradePlanStatus.TRIGGERED, reason="triggered")
    repo.append_event(
        __import__("tradingagents.trade_lifecycle", fromlist=["TradePlanEvent"]).TradePlanEvent(
            plan_id=completed_order.plan_id,
            event_type="order_result",
            status="ok",
            payload={"success": True, "client_order_id": "ata-test"},
        )
    )

    result = reconcile_plans(repo)

    assert result["checked"] == 2
    assert repo.get_plan(missing_order.plan_id).status == TradePlanStatus.NEEDS_RECONCILIATION
    assert repo.get_plan(completed_order.plan_id).status == TradePlanStatus.EXECUTED

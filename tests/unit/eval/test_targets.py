from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tradingagents.alpha_discovery.models import DiscoveryBatch, Handoff, OpportunityCandidate
from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository
from tradingagents.eval import EpisodeLedger
from tradingagents.eval.targets import EvaluationTargetBuilder, TargetAwareRewardResolver, build_target_report
from tradingagents.trade_lifecycle import ConditionalTradePlan, TradePlanEvent, TradePlanRepository


class SyntheticPriceProvider:
    def __init__(self, returns):
        self.returns = returns

    def fetch_return(self, symbol: str, start_date: date, holding_days: int) -> float | None:
        return self.returns.get(symbol)


def _future(days: int = 10) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _completed_episode(ledger: EpisodeLedger, run_id: str = "run-1", action: str = "HOLD") -> None:
    ledger.start_episode(
        run_id,
        "AAPL",
        "2026-01-02",
        {"trading_horizon": "position"},
        ["market"],
    )
    ledger.complete_episode(
        run_id,
        {
            "trading_horizon": "position",
            "trading_mode": "investment",
            "final_trade_decision": f"**Action**: {action}\nFINAL TRANSACTION PROPOSAL: **{action}**",
        },
        action,
        None,
    )


def _plan(**overrides) -> ConditionalTradePlan:
    payload = {
        "plan_id": "plan-1",
        "symbol": "AAPL",
        "action": "BUY",
        "trigger": {"type": "market"},
        "invalidation": {"price_below": 95.0},
        "valid_until": _future(),
        "source_run_id": "run-1",
        "horizon": "position",
        "execution_policy": {"notional": 500, "paper_only": True},
    }
    payload.update(overrides)
    return ConditionalTradePlan(**payload)


def test_final_hold_and_conditional_buy_generate_separate_targets(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    trade_repo = TradePlanRepository(tmp_path / "trade.sqlite")
    _completed_episode(ledger)
    trade_repo.upsert_plan(_plan())

    targets = EvaluationTargetBuilder(ledger, trade_repository=trade_repo).build_all()
    stored = {row["target_type"]: row for row in ledger.list_evaluation_targets()}

    assert len(targets) == 2
    assert stored["final_action"]["action"] == "HOLD"
    assert stored["conditional_plan"]["action"] == "BUY"
    assert stored["conditional_plan"]["trigger_status"] == "not_triggered"
    assert stored["conditional_plan"]["execution_status"] == "not_ordered"


def test_triggered_conditional_buy_target_is_generated_without_order(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    trade_repo = TradePlanRepository(tmp_path / "trade.sqlite")
    _completed_episode(ledger)
    plan = trade_repo.upsert_plan(_plan(status="needs_review"))
    trade_repo.append_event(
        TradePlanEvent(
            plan_id=plan.plan_id,
            event_type="trigger_review_required",
            status="waiting",
            payload={"observation": {"observed_at": "2026-01-05T15:00:00Z", "price": 101.0}},
            created_at="2026-01-05T15:00:00Z",
        )
    )

    EvaluationTargetBuilder(ledger, trade_repository=trade_repo).build_all()
    targets = {row["target_type"]: row for row in ledger.list_evaluation_targets()}

    assert targets["conditional_plan"]["trigger_status"] == "triggered"
    assert targets["triggered_conditional_plan"]["action"] == "BUY"
    assert targets["triggered_conditional_plan"]["anchor_date"] == "2026-01-05"
    assert targets["triggered_conditional_plan"]["execution_status"] == "needs_review"


def test_position_holding_days_and_valid_until_do_not_override_target_holding_period(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    trade_repo = TradePlanRepository(tmp_path / "trade.sqlite")
    _completed_episode(ledger)
    trade_repo.upsert_plan(_plan(valid_until="2026-01-03T00:00:00Z"))

    EvaluationTargetBuilder(ledger, trade_repository=trade_repo).build_all()
    conditional = [row for row in ledger.list_evaluation_targets() if row["target_type"] == "conditional_plan"][0]

    assert conditional["holding_days"] == 63
    assert conditional["metadata_json"]["valid_until"] == "2026-01-03T00:00:00Z"


def test_execution_status_is_component_context_not_scoring_filter(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    trade_repo = TradePlanRepository(tmp_path / "trade.sqlite")
    _completed_episode(ledger)
    trade_repo.upsert_plan(_plan(status="cancelled"))
    EvaluationTargetBuilder(ledger, trade_repository=trade_repo).build_all()

    resolved = TargetAwareRewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": 0.10, "SPY": 0.02}),
        config={"eval_neutral_band_bps": {"position": 300}},
    ).score_due_targets(as_of="2026-04-15", filters={"target_type": "conditional_plan"})

    assert len(resolved) == 1
    assert resolved[0].evaluation_status == "resolved"
    assert resolved[0].components_json["execution_status"] == "cancelled"
    assert resolved[0].reward_scalar is not None


def test_ad_to_ata_to_conditional_to_trigger_resolution_report(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    trade_repo = TradePlanRepository(tmp_path / "trade.sqlite")
    ad_repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    ad_repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-01-01T00:00:00Z"))
    ad_repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="cand-1",
            batch_id="batch-1",
            ticker="AAPL",
            tier="A",
            alpha_score=0.9,
            opportunity_type="continuation",
            direction_hint="bullish",
        ),
        updated_at="2026-01-01T00:00:00Z",
    )
    ad_repo.upsert_handoff(Handoff("cand-1", "run-1", "completed", "2026-01-02T00:00:00Z", "HOLD", plan_id="plan-1"))
    _completed_episode(ledger)
    plan = trade_repo.upsert_plan(_plan(status="needs_review"))
    trade_repo.append_event(
        TradePlanEvent(
            plan_id=plan.plan_id,
            event_type="trigger_review_required",
            status="waiting",
            payload={"observation": {"observed_at": "2026-01-05T15:00:00Z"}},
            created_at="2026-01-05T15:00:00Z",
        )
    )

    EvaluationTargetBuilder(ledger, trade_repository=trade_repo, alpha_repository=ad_repo).build_all()
    TargetAwareRewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": 0.10, "SPY": 0.02}),
        config={"eval_neutral_band_bps": {"position": 300}},
    ).score_due_targets(as_of="2026-04-15")
    report = build_target_report(ledger, group_by=["target_type"])

    groups = {row["group"]["target_type"]: row for row in report}
    assert groups["final_action"]["missed_opportunity_count"] == 1
    assert groups["conditional_plan"]["resolved"] == 1
    assert groups["triggered_conditional_plan"]["resolved"] == 1
    assert groups["ad_candidate"]["resolved"] == 1

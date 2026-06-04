from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import CriticRecordV1, EpisodeLedger, RewardRecordV1
from tradingagents.eval.harness import build_harness_report, build_hypothesis_report


def _suite_file(tmp_path: Path) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "suite_id": "benchmark:harness:test:v1",
                "cases": [
                    {"case_id": f"case-{idx}", "symbol": "AAPL", "trade_date": f"2026-01-0{idx}", "horizon": "swing"}
                    for idx in range(1, 4)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _seed_run(
    ledger: EpisodeLedger,
    run_id: str,
    *,
    trade_date: str,
    final_action: str,
    trader_action: str = "BUY",
    reward: float | None = 0.1,
    alpha: float | None = 0.05,
    tags: list[str] | None = None,
    prompt_version: str = "v1",
) -> None:
    final_state = {
        "investment_plan": f"**Recommendation**: {trader_action}\nFINAL TRANSACTION PROPOSAL: **{trader_action}**",
        "trader_investment_plan": f"**Action**: {trader_action}\nFINAL TRANSACTION PROPOSAL: **{trader_action}**",
        "final_trade_decision": f"**Action**: {final_action}\nFINAL TRANSACTION PROPOSAL: **{final_action}**",
        "trading_mode": "investment",
        "trading_horizon": "swing",
    }
    ledger.start_episode(
        run_id,
        "AAPL",
        trade_date,
        {"prompt_version": prompt_version, "online_tools": False},
        ["market"],
        metadata={"data_leakage_risk": "low"},
    )
    ledger.complete_episode(run_id, final_state, final_action, None)
    if reward is not None:
        ledger.upsert_reward(
            RewardRecordV1(
                run_id=run_id,
                reward_version="v1",
                holding_days=5,
                raw_return=alpha or 0,
                benchmark_return=0.0,
                alpha_return=alpha,
                oracle_label="BUY" if (alpha or 0) > 0 else "HOLD",
                classification_reward=0.0,
                pnl_reward=reward,
                reward_scalar=reward,
                components_json={
                    "counterfactual_rewards": {
                        "final_action": {"action": final_action, "pnl_reward": -1.0 if final_action == "HOLD" else reward},
                        "risk_manager_veto": {"action": trader_action, "pnl_reward": 0.05 if trader_action == "BUY" else 0.0},
                    }
                },
                resolved_at="2026-01-20T00:00:00Z",
                data_source="test",
            )
        )
    if tags:
        ledger.add_critic_record(
            CriticRecordV1(
                run_id=run_id,
                critic_version="v1",
                failure_tags=tags,
                evidence_spans=["final_decision-0001"],
                reward_snapshot={"reward_scalar": reward},
                reflection_text="test",
                improvement_candidates=["test"],
            )
        )


def test_hypothesis_report_returns_insufficient_sample(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_run(ledger, "run-1", trade_date="2026-01-01", final_action="HOLD", reward=None)

    report = build_hypothesis_report(ledger, min_resolved=3)

    assert report["quality"]["insufficient_sample"] is True
    assert report["hypotheses"]["H1_hold_bias"]["status"] == "insufficient_sample"
    assert report["metrics"]["pending_count"] == 1


def test_h1_supported_for_hold_heavy_downgrade_sample(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    for idx in range(1, 6):
        _seed_run(
            ledger,
            f"run-{idx}",
            trade_date=f"2026-01-0{idx}",
            final_action="HOLD",
            trader_action="BUY",
            tags=["missed_directional_move", "over_conservative_hold"],
        )

    report = build_hypothesis_report(ledger, min_resolved=5)

    assert report["hypotheses"]["H1_hold_bias"]["status"] == "supported"
    assert report["metrics"]["risk_veto_rate"] == 1.0


def test_h2_supported_for_veto_with_better_counterfactual(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    for idx in range(1, 6):
        _seed_run(
            ledger,
            f"run-{idx}",
            trade_date=f"2026-01-0{idx}",
            final_action="HOLD",
            trader_action="BUY",
            tags=["soft_gate_over_veto"],
        )

    report = build_hypothesis_report(ledger, min_resolved=5)

    assert report["hypotheses"]["H2_soft_gate_over_veto"]["status"] == "supported"
    assert report["metrics"]["avg_counterfactual_advantage"] > 0


def test_h3_supported_for_trigger_drift_tags(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    for idx in range(1, 5):
        _seed_run(ledger, f"run-{idx}", trade_date=f"2026-01-0{idx}", final_action="BUY", trader_action="BUY")
    _seed_run(
        ledger,
        "run-trigger",
        trade_date="2026-01-05",
        final_action="HOLD",
        trader_action="BUY",
        tags=["moving_trigger", "trigger_met_but_no_action"],
    )

    report = build_hypothesis_report(ledger, min_resolved=5)

    assert report["hypotheses"]["H3_trigger_drift"]["status"] == "supported"
    assert report["metrics"]["trigger_drift_rate"] == 0.2


def test_harness_report_filters_suite_and_variant(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_run(ledger, "run-1", trade_date="2026-01-01", final_action="BUY", prompt_version="v1")
    _seed_run(ledger, "run-2", trade_date="2026-01-02", final_action="HOLD", prompt_version="v2")
    _seed_run(ledger, "run-3", trade_date="2026-01-03", final_action="BUY", prompt_version="v1")

    report = build_harness_report(
        ledger,
        suite_path=_suite_file(tmp_path),
        variant_filter={"prompt_version": "v1"},
        min_resolved=1,
    )

    assert report["report_type"] == "eval_harness_report"
    assert report["suite"]["case_count"] == 3
    assert report["metrics"]["sample_count"] == 2
    assert report["sample"]["representative_runs"][0]["case_id"] == "case-1"


def test_harness_report_can_include_baseline_candidate_comparison(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_run(ledger, "baseline-1", trade_date="2026-01-01", final_action="BUY", prompt_version="v1", reward=0.1)
    _seed_run(ledger, "candidate-1", trade_date="2026-01-01", final_action="HOLD", prompt_version="v2", reward=0.2)

    report = build_harness_report(
        ledger,
        suite_path=_suite_file(tmp_path),
        baseline_filter={"prompt_version": "v1"},
        candidate_filter={"prompt_version": "v2"},
        min_resolved=1,
    )

    assert report["comparison"]["summary"]["compared"] == 1
    assert report["comparison"]["case_diffs"][0]["action_changed"] is True

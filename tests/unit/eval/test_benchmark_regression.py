from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import EpisodeLedger, RewardRecordV1
from tradingagents.eval.benchmarking import compare_existing_runs, load_benchmark_suite


def _suite_file(tmp_path: Path) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "suite_id": "benchmark:position:core:v1",
                "cases": [
                    {
                        "case_id": "case:AAPL:2026-05-20:position",
                        "symbol": "AAPL",
                        "trade_date": "2026-05-20",
                        "horizon": "position",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _seed_variant(
    ledger: EpisodeLedger,
    tmp_path: Path,
    run_id: str,
    prompt_version: str,
    action: str,
    confidence: str,
    reward: float,
    *,
    high_leakage: bool = False,
) -> None:
    audit_path = tmp_path / f"{run_id}.json"
    audit_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "symbol": "AAPL",
                "trade_date": "2026-05-20",
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    final_state = {
        "final_trade_decision": f"**Action**: {action}\n**Confidence**: {confidence}\nFINAL TRANSACTION PROPOSAL: **{action}**",
        "trading_horizon": "position",
    }
    ledger.start_episode(
        run_id,
        "AAPL",
        "2026-05-20",
        {"prompt_version": prompt_version, "online_tools": high_leakage},
        ["market"],
        metadata={"data_leakage_risk": "high" if high_leakage else "low"},
    )
    ledger.complete_episode(run_id, final_state, action, str(audit_path))
    ledger.upsert_reward(
        RewardRecordV1(
            run_id=run_id,
            reward_version="v1",
            holding_days=5,
            raw_return=reward,
            benchmark_return=0.0,
            alpha_return=reward,
            oracle_label=action,
            classification_reward=1.0,
            pnl_reward=reward,
            reward_scalar=reward,
            components_json={},
            resolved_at="2026-05-30T00:00:00Z",
            data_source="test",
        )
    )


def test_compare_existing_runs_reports_deterministic_diffs(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_variant(ledger, tmp_path, "baseline", "v1", "BUY", "medium", 0.1)
    _seed_variant(ledger, tmp_path, "candidate", "v2", "HOLD", "high", 0.3)
    suite = load_benchmark_suite(_suite_file(tmp_path))

    result = compare_existing_runs(
        ledger,
        suite,
        baseline_filter={"prompt_version": "v1"},
        candidate_filter={"prompt_version": "v2"},
    )

    diff = result["case_diffs"][0]
    assert result["summary"]["compared"] == 1
    assert diff["action_changed"] is True
    assert diff["confidence_delta"] == 0.25
    assert diff["reward_delta"] == 0.19999999999999998


def test_compare_existing_runs_excludes_high_leakage_by_default(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_variant(ledger, tmp_path, "baseline", "v1", "BUY", "medium", 0.1)
    _seed_variant(ledger, tmp_path, "candidate", "v2", "HOLD", "high", 0.3, high_leakage=True)
    suite = load_benchmark_suite(_suite_file(tmp_path))

    result = compare_existing_runs(
        ledger,
        suite,
        baseline_filter={"prompt_version": "v1"},
        candidate_filter={"prompt_version": "v2"},
    )

    assert result["missing_cases"][0]["missing_candidate"] is True

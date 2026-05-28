from __future__ import annotations

from tradingagents.eval import CriticRecordV1, EpisodeLedger, RewardRecordV1
from tradingagents.eval.memory_v2 import (
    create_memory_candidates_from_critic,
    demote_memory,
    memory_ablation,
    memory_report,
    promote_memory,
    retrieve_memory,
)


FINAL_STATE = {
    "final_trade_decision": "**Action**: BUY\n**Confidence**: high\nFINAL TRANSACTION PROPOSAL: **BUY**",
    "trading_mode": "investment",
    "trading_horizon": "position",
}


def _seed_critic_episode(tmp_path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode(
        "run-1",
        "AAPL",
        "2026-05-20",
        {"trading_horizon": "position", "online_tools": False},
        ["market"],
    )
    ledger.complete_episode("run-1", FINAL_STATE, "BUY", None)
    ledger.upsert_reward(
        RewardRecordV1(
            run_id="run-1",
            reward_version="v1",
            holding_days=5,
            raw_return=-0.05,
            benchmark_return=0.01,
            alpha_return=-0.06,
            oracle_label="SELL",
            classification_reward=-1.0,
            pnl_reward=-0.05,
            reward_scalar=-0.5,
            components_json={},
            resolved_at="2026-05-30T00:00:00Z",
            data_source="test",
        )
    )
    ledger.add_critic_record(
        CriticRecordV1(
            run_id="run-1",
            critic_version="v1",
            failure_tags=["wrong_direction", "underperformed_benchmark"],
            evidence_spans=["final_decision-0001"],
            reward_snapshot={"reward_scalar": -0.5},
            reflection_text="Final action BUY disagreed with outcome label SELL.",
            improvement_candidates=["Check risk override."],
        )
    )
    return ledger


def test_candidate_creation_from_critic_stays_candidate(tmp_path):
    ledger = _seed_critic_episode(tmp_path)

    candidates = create_memory_candidates_from_critic(ledger, run_id="run-1")

    assert candidates[0]["state"] == "candidate"
    assert candidates[0]["symbol"] == "AAPL"
    assert candidates[0]["horizon"] == "position"
    assert candidates[0]["source_run_id"] == "run-1"
    stored = ledger.list_memory_items(run_id="run-1")[0]
    assert stored["state"] == "candidate"
    assert stored["created_by"] == "critic:v1"


def test_promotion_requires_supporting_refs_and_retrieval_audit(tmp_path):
    ledger = _seed_critic_episode(tmp_path)
    candidate = create_memory_candidates_from_critic(ledger, run_id="run-1")[0]

    promoted = promote_memory(
        ledger,
        memory_id=candidate["memory_id"],
        reason="resolved outcome supports this lesson",
        promoted_by="test",
    )
    retrieval = retrieve_memory(
        ledger,
        run_id="run-1",
        stage="risk_manager",
        policy="ticker_horizon_promoted_v1",
    )

    assert promoted["state"] == "promoted"
    assert retrieval["summary"]["retrieved_count"] == 1
    assert retrieval["items"][0]["untrusted"] is False
    report = memory_report(ledger, symbol="AAPL", horizon="position")
    assert report["summary"]["by_state"] == {"promoted": 1}


def test_demote_records_reason_and_ablation_is_deterministic(tmp_path):
    ledger = _seed_critic_episode(tmp_path)
    candidate = create_memory_candidates_from_critic(ledger, run_id="run-1")[0]
    promote_memory(
        ledger,
        memory_id=candidate["memory_id"],
        reason="manual review",
        promoted_by="test",
    )
    retrieve_memory(ledger, run_id="run-1", stage="risk_manager", policy="ticker_horizon_promoted_v1")

    demoted = demote_memory(
        ledger,
        memory_id=candidate["memory_id"],
        reason="retrieval correlated with negative reward",
    )
    ablation = memory_ablation(
        ledger,
        since="2026-01-01",
        policies=["none", "ticker_horizon_promoted_v1"],
    )

    assert demoted["state"] == "demoted"
    assert ablation["summary"]["policies"] == 2
    assert ablation["policies"][1]["retrieved_count"] == 1


def test_candidate_policy_returns_untrusted_candidates(tmp_path):
    ledger = _seed_critic_episode(tmp_path)
    create_memory_candidates_from_critic(ledger, run_id="run-1")

    retrieval = retrieve_memory(
        ledger,
        run_id="run-1",
        stage="risk_manager",
        policy="ticker_horizon_candidates_v1",
    )

    assert retrieval["items"][0]["state"] == "candidate"
    assert retrieval["items"][0]["untrusted"] is True

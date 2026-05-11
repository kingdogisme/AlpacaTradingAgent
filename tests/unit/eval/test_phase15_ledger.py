from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import (
    CriticRecordV1,
    EpisodeLedger,
    MemoryItemRecordV1,
    MemoryPromotionRecordV1,
)
from tradingagents.eval.ledger import stable_config_hash


FINAL_STATE = {
    "final_trade_decision": "**Action**: BUY\n**Confidence**: high\nFINAL TRANSACTION PROPOSAL: **BUY**",
    "trading_mode": "investment",
    "trading_horizon": "swing",
}


def _audit_file(tmp_path: Path, run_id: str) -> Path:
    path = tmp_path / f"{run_id}.json"
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "ended_at": "2026-01-02T16:00:00Z",
                "summary": {"final_signal": "BUY"},
                "events": [
                    {
                        "timestamp": "2026-01-02T15:00:00Z",
                        "type": "prompt",
                        "payload": {"report_type": "market_report", "prompt_text": "do not export me"},
                    },
                    {
                        "timestamp": "2026-01-02T15:01:00Z",
                        "type": "tool_call",
                        "payload": {
                            "tool_name": "get_prices",
                            "agent_type": "market",
                            "inputs": {"symbol": "AAPL"},
                            "output": "do not export me",
                            "status": "success",
                            "execution_time_seconds": 0.25,
                        },
                    },
                    {
                        "timestamp": "2026-01-02T15:02:00Z",
                        "type": "node_execution",
                        "payload": {"node_name": "market", "status": "success", "elapsed_seconds": 0.4},
                    },
                ],
                "snapshots": {"final_state": FINAL_STATE},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_trace_normalization_uses_artifact_refs_without_payload_duplication(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    audit_path = _audit_file(tmp_path, "run-1")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {}, ["market"])
    ledger.complete_episode("run-1", FINAL_STATE, "BUY", str(audit_path))

    spans = ledger.list_trace_spans("run-1")

    assert [span["span_type"] for span in spans] == [
        "prompt",
        "tool_call",
        "node_event",
        "final_decision",
    ]
    assert spans[0]["artifact_ref"] == str(audit_path)
    assert "prompt_text" not in spans[0]["metadata_json"]
    assert "output" not in spans[1]["metadata_json"]
    assert spans[-1]["metadata_json"]["final_signal"] == "BUY"


def test_config_hash_is_order_insensitive_and_experiment_is_recorded(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")

    first = stable_config_hash({"b": 2, "a": 1, "openai_api_key": "secret-a"})
    second = stable_config_hash({"a": 1, "b": 2, "openai_api_key": "secret-b"})

    assert first == second

    ledger.start_episode(
        "run-1",
        "AAPL",
        "2026-01-02",
        {
            "llm_provider": "openai",
            "quick_think_llm": "quick",
            "deep_think_llm": "deep",
            "online_tools": False,
        },
        ["market", "news"],
    )
    episode = ledger.load_episode("run-1")

    assert episode["experiment"]["config_hash"]
    assert episode["experiment"]["quick_model"] == "quick"
    assert episode["experiment"]["selected_analysts"] == ["market", "news"]
    assert episode["experiment"]["leakage_risk"] == "low"


def test_memory_item_retrieval_and_promotion_are_idempotent(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {}, ["market"])
    item = MemoryItemRecordV1(
        memory_item_id="mem-1",
        memory_type="semantic_candidate",
        content="Prefer benchmark-relative evidence.",
        source="critic",
        evidence_json={"run_id": "run-1"},
    )

    ledger.add_memory_item(item)
    ledger.add_memory_item(item)
    ledger.record_memory_retrieval("run-1", "mem-1", "trader", 1, 0.9)
    ledger.record_memory_retrieval("run-1", "mem-1", "trader", 2, 0.8)
    ledger.add_memory_promotion(
        MemoryPromotionRecordV1(
            memory_item_id="mem-1",
            from_status="candidate",
            to_status="promoted",
            reason="manual approval",
            promoted_by="test",
        )
    )

    items = ledger.list_memory_items(run_id="run-1")
    assert len(items) == 1
    assert items[0]["status"] == "promoted"


def test_critic_record_roundtrip_and_report_failure_tags(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {}, ["market"])
    ledger.complete_episode("run-1", FINAL_STATE, "BUY", None)
    ledger.add_critic_record(
        CriticRecordV1(
            run_id="run-1",
            critic_version="v1",
            failure_tags=["wrong_direction", "underperformed_benchmark"],
            evidence_spans=["final_decision-0001"],
            reward_snapshot={"reward_scalar": -0.5},
            reflection_text="Bad direction.",
            improvement_candidates=["Check override."],
        )
    )

    records = ledger.list_critic_records("run-1")
    rows = ledger.report_rows()

    assert records[0]["failure_tags"] == ["wrong_direction", "underperformed_benchmark"]
    assert "wrong_direction" in rows[0]["critic_failure_tags"]

from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.indexing import build_quality_index, build_run_index


FINAL_STATE = {
    "final_trade_decision": "**Action**: BUY\n**Confidence**: high\nFINAL TRANSACTION PROPOSAL: **BUY**",
    "trading_mode": "investment",
    "trading_horizon": "position",
}


def _audit_file(tmp_path: Path, run_id: str) -> Path:
    path = tmp_path / f"{run_id}.json"
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "symbol": "AAPL",
                "trade_date": "2026-05-20",
                "status": "completed",
                "summary": {"final_signal": "BUY"},
                "events": [
                    {
                        "timestamp": "2026-05-20T12:00:00Z",
                        "type": "tool_call",
                        "payload": {
                            "tool_name": "get_alpaca_data",
                            "agent_type": "market",
                            "inputs": {"symbol": "AAPL"},
                            "output": "very long raw output that should not be indexed",
                            "status": "degraded",
                            "quality_details": {
                                "data_quality": {
                                    "status": "fail",
                                    "source_id": "alpaca_bars",
                                    "provider": "Alpaca",
                                    "dataset_type": "price_bars",
                                    "freshness": "fail",
                                    "accuracy": "unknown",
                                    "completeness": "pass",
                                    "flags": ["stale_source"],
                                    "observed_at": "2026-05-17",
                                    "source_age_days": 3,
                                    "criticality": "critical",
                                    "artifact_ref": "tool_call:1",
                                    "output_preview": "indexed preview",
                                }
                            },
                        },
                    }
                ],
                "snapshots": {"final_state": FINAL_STATE},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_build_run_and_quality_index_from_audit_fixture(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    audit_path = _audit_file(tmp_path, "run-1")
    ledger.start_episode(
        "run-1",
        "AAPL",
        "2026-05-20",
        {"prompt_version": "v1", "quick_think_llm": "q", "deep_think_llm": "d"},
        ["market"],
    )
    ledger.complete_episode("run-1", FINAL_STATE, "BUY", str(audit_path))

    quality_rows = build_quality_index(ledger, "run-1")
    run_row = build_run_index(ledger, "run-1")

    assert quality_rows[0]["artifact_ref"] == "tool_call:1"
    assert quality_rows[0]["output_preview"] == "indexed preview"
    assert "very long raw output" not in json.dumps(ledger.list_quality_index("run-1"))
    assert run_row["index_id"] == "run_index:run-1"
    assert run_row["quality_status"] == "fail"
    assert run_row["critical_failures"] == ["alpaca_bars"]
    assert run_row["final_action"] == "BUY"
    assert ledger.list_run_index({"run_id": "run-1", "include_high_leakage": True})[0]["prompt_version"] == "v1"


def test_missing_audit_path_indexes_unknown_without_exception(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-2", "MSFT", "2026-05-20", {}, ["market"])
    ledger.complete_episode("run-2", FINAL_STATE, "BUY", None)

    run_row = build_run_index(ledger, "run-2")

    assert run_row["quality_status"] == "unknown"
    assert run_row["flags"] == ["audit_missing"]
    assert ledger.list_quality_index("run-2") == []

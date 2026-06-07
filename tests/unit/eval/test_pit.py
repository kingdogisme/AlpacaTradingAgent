from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.pit import audit_pit_run


def _seed_pit_run(tmp_path: Path, *, observed_at: str | None, tool_name: str = "get_alpaca_data") -> EpisodeLedger:
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    quality = {
        "status": "pass",
        "source_id": "alpaca_bars",
        "provider": "Alpaca",
        "dataset_type": "price_bars",
        "freshness": "pass",
        "accuracy": "pass",
        "completeness": "pass",
        "flags": [],
        "criticality": "critical",
        "artifact_ref": "tool_call:1",
        "output_preview": "open high low close volume",
    }
    if observed_at is not None:
        quality["observed_at"] = observed_at
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "run_id": "pit-1",
                "symbol": "AAPL",
                "trade_date": "2026-01-02",
                "events": [
                    {
                        "timestamp": "2026-01-02T16:00:00Z",
                        "type": "tool_call",
                        "payload": {
                            "tool_name": tool_name,
                            "agent_type": "market",
                            "inputs": {"symbol": "AAPL", "curr_date": "2026-01-02"},
                            "quality_details": {"data_quality": quality},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ledger.start_episode(
        "pit-1",
        "AAPL",
        "2026-01-02",
        {"online_tools": False, "historical_mode": "strict", "run_policy": "pit_strict"},
        ["market"],
        metadata={"data_leakage_risk": "low", "run_policy": "pit_strict"},
    )
    ledger.complete_episode("pit-1", {"final_trade_decision": "**Action**: HOLD"}, "HOLD", str(audit_path))
    return ledger


def test_pit_audit_flags_future_observed_at(tmp_path: Path):
    ledger = _seed_pit_run(tmp_path, observed_at="2026-01-03")

    report = audit_pit_run(ledger, run_id="pit-1")

    assert report["status"] == "fail"
    assert report["leakage_risk"] == "high"
    assert report["summary"]["leak_count"] == 1
    assert report["recommended_action"] == "exclude_from_main_benchmark"


def test_pit_audit_accepts_timestamped_historical_input(tmp_path: Path):
    ledger = _seed_pit_run(tmp_path, observed_at="2026-01-02")

    report = audit_pit_run(ledger, run_id="pit-1")

    assert report["status"] == "pass"
    assert report["trust_tier"] == "current_pit_rerun"


def test_pit_audit_strict_rejects_missing_required_timestamp(tmp_path: Path):
    ledger = _seed_pit_run(tmp_path, observed_at=None)

    report = audit_pit_run(ledger, run_id="pit-1")

    assert report["status"] == "fail"
    assert report["summary"]["unverifiable_strict_count"] == 1

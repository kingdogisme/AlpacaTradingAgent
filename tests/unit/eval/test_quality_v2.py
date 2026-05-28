from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.indexing import build_quality_index
from tradingagents.eval.quality_v2 import build_source_reliability, reconcile_quality


FINAL_STATE = {
    "final_trade_decision": "**Action**: HOLD\nFINAL TRANSACTION PROPOSAL: **HOLD**",
    "trading_horizon": "position",
}


def _audit_file(tmp_path: Path, run_id: str, events: list[dict]) -> Path:
    path = tmp_path / f"{run_id}.json"
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "symbol": "AAPL",
                "trade_date": "2026-05-20",
                "events": events,
            }
        ),
        encoding="utf-8",
    )
    return path


def _tool_event(index: int, source_id: str, preview: str, status: str = "pass", flags=None):
    return {
        "timestamp": "2026-05-20T12:00:00Z",
        "type": "tool_call",
        "payload": {
            "tool_name": f"tool_{index}",
            "agent_type": "market",
            "inputs": {"symbol": "AAPL"},
            "status": "success",
            "quality_details": {
                "data_quality": {
                    "status": status,
                    "source_id": source_id,
                    "provider": source_id,
                    "dataset_type": "price_bars",
                    "freshness": "pass",
                    "accuracy": "unknown",
                    "completeness": "pass",
                    "flags": flags or [],
                    "criticality": "critical",
                    "artifact_ref": f"tool_call:{index}",
                    "output_preview": preview,
                }
            },
        },
    }


def _seed_run(tmp_path: Path, events: list[dict]) -> EpisodeLedger:
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    audit_path = _audit_file(tmp_path, "run-q", events)
    ledger.start_episode("run-q", "AAPL", "2026-05-20", {"online_tools": False}, ["market"])
    ledger.complete_episode("run-q", FINAL_STATE, "HOLD", str(audit_path))
    build_quality_index(ledger, "run-q")
    return ledger


def test_price_reconciliation_pass_and_warn(tmp_path):
    ledger = _seed_run(
        tmp_path,
        [
            _tool_event(1, "alpaca_bars", "latest close: 100.00"),
            _tool_event(2, "yfinance_bars", "latest close: 100.50"),
        ],
    )

    result = reconcile_quality(ledger, "run-q")

    check = result["reconciliation_checks"][0]
    assert check["status"] == "pass"
    assert check["delta_pct"] == 0.5

    ledger = _seed_run(
        tmp_path / "warn",
        [
            _tool_event(1, "alpaca_bars", "latest close: 100.00"),
            _tool_event(2, "yfinance_bars", "latest close: 103.00"),
        ],
    )
    result = reconcile_quality(ledger, "run-q")
    check = result["reconciliation_checks"][0]
    assert check["status"] == "warn"
    assert "cross_source_price_mismatch" in check["flags"]


def test_missing_secondary_and_extraction_unknown_do_not_fail(tmp_path):
    ledger = _seed_run(tmp_path, [_tool_event(1, "alpaca_bars", "no price here")])

    result = reconcile_quality(ledger, "run-q")

    assert result["observations"][0]["extraction_status"] == "unknown"
    assert result["reconciliation_checks"][0]["status"] == "unknown"
    assert "missing_secondary_source" in result["reconciliation_checks"][0]["flags"]


def test_sec_precedence_and_reliability_aggregation(tmp_path):
    events = [
        _tool_event(1, "alpaca_bars", "latest close: 100", status="warn", flags=["fallback_used"]),
        _tool_event(2, "yfinance_bars", "latest close: 102"),
    ]
    sec = _tool_event(3, "sec_edgar_fundamentals", "official filing")
    sec["payload"]["quality_details"]["data_quality"]["dataset_type"] = "filings"
    av = _tool_event(4, "alpha_vantage_fundamentals", "supplemental facts")
    av["payload"]["quality_details"]["data_quality"]["dataset_type"] = "fundamentals"
    events.extend([sec, av])
    ledger = _seed_run(tmp_path, events)

    result = reconcile_quality(ledger, "run-q")
    reliability = build_source_reliability(ledger, windows=(30,))

    assert any(item["check_type"] == "sec_precedence" for item in result["reconciliation_checks"])
    alpaca = next(item for item in reliability if item["source_id"] == "alpaca_bars")
    assert alpaca["quality_warn"] >= 1
    assert alpaca["fallback_count"] >= 1

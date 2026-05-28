from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app
from tradingagents.eval import EpisodeLedger


def _seed_cli_quality(tmp_path: Path) -> Path:
    db_path = tmp_path / "eval.sqlite"
    ledger = EpisodeLedger(db_path)
    audit_path = tmp_path / "audit.json"
    events = []
    for idx, (source, close) in enumerate((("alpaca_bars", 100), ("yfinance_bars", 103)), start=1):
        events.append(
            {
                "timestamp": "2026-05-20T12:00:00Z",
                "type": "tool_call",
                "payload": {
                    "tool_name": f"tool_{idx}",
                    "agent_type": "market",
                    "inputs": {"symbol": "AAPL"},
                    "status": "success",
                    "quality_details": {
                        "data_quality": {
                            "status": "pass",
                            "source_id": source,
                            "provider": source,
                            "dataset_type": "price_bars",
                            "freshness": "pass",
                            "accuracy": "unknown",
                            "completeness": "pass",
                            "flags": [],
                            "criticality": "critical",
                            "artifact_ref": f"tool_call:{idx}",
                            "output_preview": f"latest close: {close}",
                        }
                    },
                },
            }
        )
    audit_path.write_text(json.dumps({"run_id": "run-cli-q", "events": events}), encoding="utf-8")
    ledger.start_episode("run-cli-q", "AAPL", "2026-05-20", {"online_tools": False}, ["market"])
    ledger.complete_episode(
        "run-cli-q",
        {"final_trade_decision": "**Action**: HOLD", "trading_horizon": "position"},
        "HOLD",
        str(audit_path),
    )
    return db_path


def test_quality_v2_cli_json_contracts(tmp_path: Path, monkeypatch):
    db_path = _seed_cli_quality(tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "episode_ledger_path", str(db_path))
    runner = CliRunner()

    reconcile = runner.invoke(app, ["quality-reconcile", "--run-id", "run-cli-q", "--format", "json"])
    index = runner.invoke(
        app,
        ["quality-index", "--run-id", "run-cli-q", "--include-reconciliation", "--format", "json"],
    )
    reliability = runner.invoke(app, ["source-reliability", "--window-days", "30", "--format", "json"])

    assert reconcile.exit_code == 0
    assert index.exit_code == 0
    assert reliability.exit_code == 0
    reconcile_payload = json.loads(reconcile.stdout)
    index_payload = json.loads(index.stdout)
    reliability_payload = json.loads(reliability.stdout)
    assert reconcile_payload["summary"]["warn"] == 1
    assert "observations" in index_payload
    assert reliability_payload["summary"]["records"] >= 2

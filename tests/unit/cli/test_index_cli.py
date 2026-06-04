from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app
from tradingagents.eval import EpisodeLedger


def _seed_cli_run(tmp_path: Path) -> Path:
    db_path = tmp_path / "eval.sqlite"
    ledger = EpisodeLedger(db_path)
    audit_path = tmp_path / "run-cli.json"
    audit_path.write_text(
        json.dumps(
            {
                "run_id": "run-cli",
                "symbol": "AAPL",
                "trade_date": "2026-05-20",
                "events": [
                    {
                        "timestamp": "2026-05-20T12:00:00Z",
                        "type": "tool_call",
                        "payload": {
                            "tool_name": "get_alpaca_data",
                            "agent_type": "market",
                            "inputs": {"symbol": "AAPL"},
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
                                    "criticality": "critical",
                                    "artifact_ref": "tool_call:1",
                                    "output_preview": "preview",
                                }
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    final_state = {
        "final_trade_decision": "**Action**: BUY\n**Confidence**: high\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "trading_horizon": "position",
    }
    ledger.start_episode("run-cli", "AAPL", "2026-05-20", {"prompt_version": "v1", "online_tools": False}, ["market"])
    ledger.complete_episode("run-cli", final_state, "BUY", str(audit_path))
    return db_path


def test_index_cli_json_contracts(tmp_path: Path, monkeypatch):
    db_path = _seed_cli_run(tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "episode_ledger_path", str(db_path))
    runner = CliRunner()

    run_result = runner.invoke(app, ["run-index", "--run-id", "run-cli", "--format", "json"])
    quality_result = runner.invoke(app, ["quality-index", "--run-id", "run-cli", "--format", "json"])
    pack_result = runner.invoke(
        app,
        ["retrieval-pack", "--type", "risk_review", "--run-id", "run-cli", "--format", "json"],
    )

    assert run_result.exit_code == 0
    assert quality_result.exit_code == 0
    assert pack_result.exit_code == 0
    run_payload = json.loads(run_result.stdout)
    quality_payload = json.loads(quality_result.stdout)
    pack_payload = json.loads(pack_result.stdout)
    assert run_payload["summary"]["records"] == 1
    assert run_payload["records"][0]["quality_status"] == "fail"
    assert quality_payload["records"][0]["artifact_ref"] == "tool_call:1"
    assert pack_payload["summary"]["quality_status"] == "fail"


def test_run_index_filters_by_final_action(tmp_path: Path, monkeypatch):
    db_path = _seed_cli_run(tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "episode_ledger_path", str(db_path))
    runner = CliRunner()

    result = runner.invoke(app, ["run-index", "--action", "BUY", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["records"] == 1
    assert payload["records"][0]["final_action"] == "BUY"


def test_buy_runs_cli_lists_buy_cases(tmp_path: Path, monkeypatch):
    db_path = _seed_cli_run(tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "episode_ledger_path", str(db_path))
    runner = CliRunner()

    result = runner.invoke(app, ["buy-runs", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["final_action"] == "BUY"
    assert payload["records"][0]["run_id"] == "run-cli"

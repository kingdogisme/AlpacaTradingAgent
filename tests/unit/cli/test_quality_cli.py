from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app


def _audit_payload(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "run-q",
                "symbol": "AAPL",
                "trade_date": "2026-05-20",
                "events": [
                    {
                        "timestamp": "2026-05-20T12:00:00Z",
                        "type": "tool_call",
                        "payload": {
                            "tool_name": "get_alpaca_data",
                            "agent_type": "MARKET",
                            "inputs": {"symbol": "AAPL"},
                            "output": "raw output",
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
                                    "output_preview": "raw output",
                                }
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_quality_summary_json_contract(tmp_path):
    runner = CliRunner()
    audit_path = _audit_payload(tmp_path)

    result = runner.invoke(app, ["quality-summary", "--audit-path", str(audit_path), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "run-q"
    assert payload["summary"]["quality_fail"] == 1
    assert payload["top_risks"][0]["artifact_ref"] == "tool_call:1"
    assert payload["recommended_debug_queries"]


def test_quality_events_and_open(tmp_path):
    runner = CliRunner()
    audit_path = _audit_payload(tmp_path)

    events = runner.invoke(app, ["quality-events", "--audit-path", str(audit_path), "--status", "fail"])
    opened = runner.invoke(app, ["quality-open", "--audit-path", str(audit_path), "--artifact-ref", "tool_call:1", "--no-include-output"])

    assert events.exit_code == 0
    assert json.loads(events.stdout.strip())["source_id"] == "alpaca_bars"
    assert opened.exit_code == 0
    payload = json.loads(opened.stdout)
    assert payload["output"] == "<redacted:10_chars>"

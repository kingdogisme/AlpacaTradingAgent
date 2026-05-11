from __future__ import annotations

import json

from tradingagents.run_logger import RunAuditLogger


def test_run_logger_persists_completed_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("AAPL", "2026-01-02", config={"online_tools": False})
    logger.log_prompt("market_report", "Prompt body", symbol="AAPL", run_id=run_id)
    logger.log_tool_call(
        "fake_tool",
        {"ticker": "AAPL"},
        "tool output",
        "success",
        0.25,
        agent_type="Market",
        symbol="AAPL",
        run_id=run_id,
    )
    logger.finish_run(
        symbol="AAPL",
        run_id=run_id,
        status="completed",
        final_state={"final_trade_decision": "FINAL TRANSACTION PROPOSAL: **BUY**"},
        final_signal="BUY",
    )

    run_file = next((tmp_path / "eval_results" / "AAPL" / "TradingAgentsStrategy_logs" / "runs").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["status"] == "completed"
    assert payload["summary"]["prompt_events"] == 1
    assert payload["summary"]["tool_events"] == 1
    assert payload["summary"]["final_signal"] == "BUY"
    assert payload["snapshots"]["final_state"]["final_trade_decision"].endswith("**BUY**")


def test_run_logger_persists_failed_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("BTC/USD", "2026-01-02")
    logger.finish_run(symbol="BTC/USD", run_id=run_id, status="failed", error_message="boom")

    run_file = next((tmp_path / "eval_results" / "BTC_USD" / "TradingAgentsStrategy_logs" / "runs").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["status"] == "failed"
    assert payload["summary"]["error_message"] == "boom"
    assert payload["summary"]["error_events"] == 1

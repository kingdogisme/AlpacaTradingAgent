from __future__ import annotations

import json

from tradingagents.run_logger import RunAuditLogger


def _run_files(root, symbol):
    return root / symbol / "TradingAgentsStrategy_logs" / "runs"


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

    run_file = next(_run_files(tmp_path / "results", "AAPL").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["status"] == "completed"
    assert payload["summary"]["prompt_events"] == 1
    assert payload["summary"]["tool_events"] == 1
    assert payload["summary"]["final_signal"] == "BUY"
    assert payload["snapshots"]["final_state"]["final_trade_decision"].endswith("**BUY**")


def test_run_logger_respects_configured_results_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    configured_results = tmp_path / "isolated-results"
    run_id = logger.start_run(
        "AAPL",
        "2026-01-02",
        config={"results_dir": str(configured_results)},
    )
    logger.finish_run(symbol="AAPL", run_id=run_id, status="completed")

    run_file = next((configured_results / "AAPL" / "TradingAgentsStrategy_logs" / "runs").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["run_id"] == run_id
    assert payload["file_path"] == str(run_file)
    assert not (tmp_path / "eval_results" / "AAPL" / "TradingAgentsStrategy_logs" / "runs").exists()


def test_run_logger_counts_llm_cache_tokens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("AAPL", "2026-01-02")
    logger.log_event(
        "llm_call",
        symbol="AAPL",
        run_id=run_id,
        payload={
            "model": "deepseek-v4",
            "model_role": "quick",
            "usage": {
                "input_tokens": 100,
                "cache_hit_tokens": 40,
                "cache_creation_tokens": 10,
                "output_tokens": 25,
                "reasoning_tokens": 5,
                "total_tokens": 125,
            }
        },
    )
    logger.finish_run(symbol="AAPL", run_id=run_id, status="completed")

    run_file = next(_run_files(tmp_path / "results", "AAPL").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["summary"]["total_llm_input_tokens"] == 100
    assert payload["summary"]["total_llm_cache_hit_tokens"] == 40
    assert payload["summary"]["total_llm_cache_miss_tokens"] == 50
    assert payload["summary"]["total_llm_cache_creation_tokens"] == 10
    assert payload["summary"]["total_llm_reasoning_tokens"] == 5
    assert payload["summary"]["llm_usage_by_model"]["deepseek-v4"]["total_llm_tokens"] == 125
    assert payload["summary"]["llm_usage_by_role"]["quick"]["total_llm_tokens"] == 125


def test_run_logger_persists_failed_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("BTC/USD", "2026-01-02")
    logger.finish_run(symbol="BTC/USD", run_id=run_id, status="failed", error_message="boom")

    run_file = next(_run_files(tmp_path / "results", "BTC_USD").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["status"] == "failed"
    assert payload["summary"]["error_message"] == "boom"
    assert payload["summary"]["error_events"] == 1


def test_run_logger_counts_degraded_tool_warnings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("SNDK", "2026-05-11")
    logger.log_tool_call(
        "get_fundamentals_openai",
        {"ticker": "SNDK", "curr_date": "2026-05-11"},
        "Fallback used because tool timeout before OpenAI fundamentals completed.",
        "degraded",
        165.0,
        agent_type="FUNDAMENTALS",
        symbol="SNDK",
        run_id=run_id,
        error_details={"error_type": "TimeoutError"},
        quality_details={"flags": ["timeout", "fallback_used"], "is_suspect": True},
    )
    logger.finish_run(symbol="SNDK", run_id=run_id, status="completed", final_signal="HOLD")

    run_file = next(_run_files(tmp_path / "results", "SNDK").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["summary"]["error_events"] == 0
    assert payload["summary"]["warning_events"] == 1
    assert payload["summary"]["degraded_tool_events"] == 1
    assert payload["summary"]["timeout_tool_events"] == 1
    assert payload["summary"]["suspect_tool_events"] == 1


def test_run_logger_counts_data_quality_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("AAPL", "2026-05-20")
    logger.log_tool_call(
        "get_alpaca_data",
        {"symbol": "AAPL"},
        "stale output",
        "degraded",
        0.1,
        agent_type="MARKET",
        symbol="AAPL",
        run_id=run_id,
        quality_details={
            "flags": ["stale_source"],
            "is_suspect": True,
            "data_quality": {
                "status": "fail",
                "source_id": "alpaca_bars",
                "criticality": "critical",
                "fallback_from": "yfinance",
                "flags": ["stale_source", "fallback_used"],
            },
        },
    )
    logger.finish_run(symbol="AAPL", run_id=run_id, status="completed")

    run_file = next(_run_files(tmp_path / "results", "AAPL").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["summary"]["quality_fail"] == 1
    assert payload["summary"]["stale_sources"] == ["alpaca_bars"]
    assert payload["summary"]["fallback_sources"] == ["alpaca_bars"]
    assert payload["summary"]["critical_failures"] == ["alpaca_bars"]


def test_run_logger_exit_snapshot_preserves_latest_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = RunAuditLogger()

    run_id = logger.start_run("MU", "2026-05-12")
    logger.log_agent_output("market_report", "Market body", symbol="MU", run_id=run_id)
    logger.log_agent_output(
        "final_trade_decision",
        "FINAL TRANSACTION PROPOSAL: **HOLD**",
        symbol="MU",
        run_id=run_id,
    )

    logger._close_active_runs_on_exit()

    run_file = next(_run_files(tmp_path / "results", "MU").glob("*.json"))
    payload = json.loads(run_file.read_text(encoding="utf-8"))

    assert payload["status"] == "aborted"
    assert payload["snapshots"]["latest_agent_outputs"]["market_report"] == "Market body"
    assert payload["snapshots"]["final_state"]["final_trade_decision"].endswith("**HOLD**")

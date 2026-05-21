from __future__ import annotations

import json

from tradingagents.agents.utils.agent_utils import Toolkit, timing_wrapper
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.run_logger import get_run_audit_logger


def test_tool_wrapper_prepends_data_quality_header_and_logs_artifact(tmp_path, monkeypatch):
    from webui.utils.state import app_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        Toolkit,
        "_config",
        {
            **DEFAULT_CONFIG,
            "data_quality_header_enabled": True,
            "tool_semantic_retry_enabled": False,
        },
    )
    app_state.tool_calls_log = []
    app_state.tool_calls_count = 0
    app_state.current_symbol = "AAPL"
    app_state.analyzing_symbol = "AAPL"
    run_id = get_run_audit_logger().start_run("AAPL", "2026-05-20")

    @timing_wrapper("MARKET", timeout_seconds=10)
    def get_alpaca_data(symbol: str, end_date: str) -> str:
        return "timestamp open high low close volume\n2026-04-01 1 2 1 1.5 1000"

    result = get_alpaca_data("AAPL", "2026-05-20")
    get_run_audit_logger().finish_run(symbol="AAPL", run_id=run_id, status="completed")

    assert result.startswith("[DATA_QUALITY]")
    assert "source_id: alpaca_bars" in result
    assert "artifact_ref: tool_call:1" in result

    tool_call = app_state.tool_calls_log[-1]
    quality = tool_call["quality_details"]["data_quality"]
    assert tool_call["status"] == "degraded"
    assert quality["status"] == "fail"
    assert quality["criticality"] == "critical"
    assert quality["artifact"]["raw_output_ref"] == "tool_call:1"

    run_file = next((tmp_path / "eval_results" / "AAPL" / "TradingAgentsStrategy_logs" / "runs").glob("*.json"))
    audit = json.loads(run_file.read_text(encoding="utf-8"))
    event = next(item for item in audit["events"] if item["type"] == "tool_call")
    assert event["payload"]["quality_details"]["data_quality"]["artifact_ref"] == "tool_call:1"
    assert event["payload"]["output"].startswith("[DATA_QUALITY]")

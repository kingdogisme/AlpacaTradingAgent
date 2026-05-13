from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


AGENT_OUTPUT_TO_REPORT = {
    "market_report": "market_report",
    "sentiment_report": "sentiment_report",
    "news_report": "news_report",
    "fundamentals_report": "fundamentals_report",
    "macro_report": "macro_report",
    "investment_plan": "research_manager_report",
    "trader_investment_plan": "trader_investment_plan",
    "final_trade_decision": "final_trade_decision",
}


def _latest_run_file(symbol: str, results_root: str | Path = "eval_results") -> Path | None:
    try:
        safe_symbol = safe_ticker_component(symbol)
    except ValueError:
        return None

    run_dir = Path(results_root) / safe_symbol / "TradingAgentsStrategy_logs" / "runs"
    if not run_dir.exists():
        return None

    run_files = [path for path in run_dir.glob("*.json") if path.is_file()]
    if not run_files:
        return None
    return max(run_files, key=lambda path: path.stat().st_mtime)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[REPORT_RECOVERY] Failed to read {path}: {exc}")
        return None
    return payload if isinstance(payload, dict) else None


def _restore_from_final_state(final_state: dict[str, Any], reports: dict[str, str]) -> None:
    for output_type, report_type in AGENT_OUTPUT_TO_REPORT.items():
        content = final_state.get(output_type)
        if content:
            reports[report_type] = content
            if output_type == "investment_plan":
                reports["investment_plan"] = content


def _restore_from_agent_output(payload: dict[str, Any], reports: dict[str, str]) -> None:
    output_type = payload.get("output_type")
    content = payload.get("content")
    if not output_type or not content:
        return

    if output_type in AGENT_OUTPUT_TO_REPORT:
        report_type = AGENT_OUTPUT_TO_REPORT[output_type]
        reports[report_type] = content
        if output_type == "investment_plan":
            reports["investment_plan"] = content
        return

    metadata = payload.get("metadata") or {}
    node_name = str(metadata.get("node_name") or "")
    latest_speaker = str(metadata.get("latest_speaker") or "")

    if output_type == "investment_debate_response":
        if "Bull" in node_name:
            reports["bull_report"] = content
        elif "Bear" in node_name:
            reports["bear_report"] = content
        elif "Research Manager" in node_name:
            reports["research_manager_report"] = content
            reports["investment_plan"] = content
    elif output_type == "risk_debate_response":
        speaker = latest_speaker or node_name
        if "Risky" in speaker:
            reports["risky_report"] = content.replace("Risky Analyst: ", "").strip()
        elif "Safe" in speaker:
            reports["safe_report"] = content.replace("Safe Analyst: ", "").strip()
        elif "Neutral" in speaker:
            reports["neutral_report"] = content.replace("Neutral Analyst: ", "").strip()


def load_latest_run_reports(symbol: str, results_root: str | Path = "eval_results") -> dict[str, Any] | None:
    """Load the latest displayable WebUI reports for a symbol from run audit logs."""
    run_file = _latest_run_file(symbol, results_root)
    if not run_file:
        return None

    payload = _read_json(run_file)
    if not payload:
        return None

    reports: dict[str, str] = {}
    prompts: dict[str, str] = {}
    snapshots = payload.get("snapshots") or {}

    latest_outputs = snapshots.get("latest_agent_outputs")
    if isinstance(latest_outputs, dict):
        _restore_from_final_state(latest_outputs, reports)

    final_state = snapshots.get("final_state")
    if isinstance(final_state, dict):
        _restore_from_final_state(final_state, reports)

    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        event_payload = event.get("payload") or {}
        if event_type == "agent_output" and isinstance(event_payload, dict):
            _restore_from_agent_output(event_payload, reports)
        elif event_type == "prompt" and isinstance(event_payload, dict):
            report_type = event_payload.get("report_type")
            prompt_text = event_payload.get("prompt_text")
            if report_type and prompt_text:
                prompts[report_type] = prompt_text

    if reports.get("final_trade_decision") and not reports.get("portfolio_decision"):
        reports["portfolio_decision"] = reports["final_trade_decision"]

    if not any(reports.values()) and not any(prompts.values()):
        return None

    return {
        "reports": reports,
        "prompts": prompts,
        "status": payload.get("status"),
        "trade_date": payload.get("trade_date"),
        "run_file": str(run_file),
        "final_signal": (payload.get("summary") or {}).get("final_signal"),
    }

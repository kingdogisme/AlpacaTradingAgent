from __future__ import annotations

import json

from webui.utils.report_recovery import load_latest_run_reports
from webui.utils.state import app_state


def setup_function():
    app_state.reset()


def test_webui_state_can_represent_trend_research_only_block():
    app_state.init_symbol_state("AAPL")
    state = app_state.get_state("AAPL")
    state["analysis_results"] = {
        "ticker": "AAPL",
        "date": "2026-05-10",
        "decision": "BUY",
        "trading_horizon": "trend",
        "trend_research_only": True,
    }
    state["trend_execution_enabled"] = False

    assert state["analysis_results"]["trend_research_only"] is True
    assert state["trend_execution_enabled"] is False


def test_finish_analysis_run_preserves_current_symbol_and_reports():
    app_state.init_symbol_state("MU")
    state = app_state.get_state("MU")
    state["current_reports"]["market_report"] = "Market report"
    app_state.current_symbol = "MU"
    app_state.analyzing_symbol = "MU"
    app_state.analysis_running = True

    app_state.finish_analysis_run()

    assert app_state.analysis_running is False
    assert app_state.analyzing_symbol is None
    assert app_state.current_symbol == "MU"
    assert app_state.get_current_state()["current_reports"]["market_report"] == "Market report"


def test_build_symbol_state_from_reports_restores_completed_final_decision():
    app_state.build_symbol_state_from_reports(
        "MU",
        {
            "market_report": "Market report",
            "trader_investment_plan": "**Action**: HOLD",
            "final_trade_decision": "FINAL TRANSACTION PROPOSAL: **HOLD**",
        },
        complete=True,
    )

    state = app_state.get_state("MU")
    assert app_state.current_symbol == "MU"
    assert state["analysis_complete"] is True
    assert state["agent_statuses"]["Portfolio Manager"] == "completed"
    assert state["current_reports"]["portfolio_decision"].endswith("**HOLD**")


def test_load_latest_run_reports_recovers_aborted_agent_outputs(tmp_path):
    run_dir = tmp_path / "eval_results" / "MU" / "TradingAgentsStrategy_logs" / "runs"
    run_dir.mkdir(parents=True)
    run_file = run_dir / "2026-05-12_run.json"
    run_file.write_text(
        json.dumps(
            {
                "status": "aborted",
                "trade_date": "2026-05-12",
                "summary": {},
                "snapshots": {},
                "events": [
                    {
                        "type": "agent_output",
                        "payload": {
                            "output_type": "market_report",
                            "content": "Market body",
                            "metadata": {"node_name": "Market Analyst"},
                        },
                    },
                    {
                        "type": "agent_output",
                        "payload": {
                            "output_type": "risk_debate_response",
                            "content": "Safe Analyst: Safe body",
                            "metadata": {"node_name": "Safe Analyst", "latest_speaker": "Safe"},
                        },
                    },
                    {
                        "type": "prompt",
                        "payload": {
                            "report_type": "final_trade_decision",
                            "prompt_text": "Final prompt",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    recovered = load_latest_run_reports("MU", tmp_path / "eval_results")

    assert recovered["status"] == "aborted"
    assert recovered["reports"]["market_report"] == "Market body"
    assert recovered["reports"]["safe_report"] == "Safe body"
    assert recovered["prompts"]["final_trade_decision"] == "Final prompt"

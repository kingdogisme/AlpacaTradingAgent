from __future__ import annotations

from webui.utils.state import app_state


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

from __future__ import annotations

from tradingagents.contracts import ResearchRequest
from tradingagents.research import ResearchService, research_report_from_legacy_state


def _legacy_state():
    return {
        "market_report": "Market report with price trend and valuation multiple context for testing.",
        "fundamentals_report": "Fundamentals report with guidance and margin evidence for testing.",
        "news_report": "News report with catalyst evidence and demand signal for testing.",
        "sentiment_report": "Social report with sentiment evidence and positioning for testing.",
        "macro_report": "Macro report with liquidity and rates context as a possible risk.",
        "investment_plan": "**Thesis**: AI demand supports revenue growth.\n**Confidence**: medium\nRisk: valuation is high.",
        "final_trade_decision": "FINAL TRANSACTION PROPOSAL: **BUY**",
    }


def test_research_report_from_legacy_state_maps_reports_without_execution_state():
    request = ResearchRequest(symbol="NVDA", trade_date="2026-06-06")
    report = research_report_from_legacy_state(
        _legacy_state(),
        request=request,
        final_signal="BUY",
        run_id="run-1",
        audit_path="/tmp/audit.json",
    )

    assert report.symbol == "NVDA"
    assert report.conclusion == "B"
    assert report.confidence == "medium"
    assert len(report.evidence_ledger) == 5
    assert report.audit_refs["run_id"] == "run-1"


def test_research_service_disables_plan_persistence_for_legacy_graph_adapter():
    captured = {}

    class FakeGraph:
        def __init__(self, selected_analysts, config, debug=False):
            captured["selected_analysts"] = selected_analysts
            captured["config"] = config
            self.last_run_id = "run-fake"

        def propagate(self, symbol, trade_date):
            return _legacy_state(), "BUY"

    request = ResearchRequest(symbol="NVDA", trade_date="2026-06-06", selected_analysts=["market"])
    result = ResearchService(config={"persist_conditional_trade_plan": True}, graph_factory=FakeGraph).run(request)

    assert captured["selected_analysts"] == ["market"]
    assert captured["config"]["persist_conditional_trade_plan"] is False
    assert captured["config"]["v2_research_only"] is True
    assert result.report.symbol == "NVDA"
    assert result.final_signal == "BUY"

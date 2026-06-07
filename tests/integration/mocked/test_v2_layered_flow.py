from __future__ import annotations

from tradingagents.contracts import PortfolioContext, ResearchRequest
from tradingagents.execution import ExecutionService
from tradingagents.eval import (
    EpisodeLedger,
    evaluate_execution_result,
    evaluate_investment_decision,
    evaluate_research_report,
)
from tradingagents.portfolio.service import PortfolioDecisionService
from tradingagents.research import ResearchService
from tradingagents.trade_lifecycle.models import ConditionalTradePlan, MarketObservation


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


class FakeGraph:
    def __init__(self, selected_analysts, config, debug=False):
        self.last_run_id = "run-v2"
        self.config = config

    def propagate(self, symbol, trade_date):
        return _legacy_state(), "BUY"


def test_v2_layered_flow_stops_before_broker_execution_by_default(tmp_path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    research = ResearchService(
        config={"alpaca_use_paper": True, "trade_lifecycle_default_notional": 500},
        graph_factory=FakeGraph,
    ).run(ResearchRequest(symbol="NVDA", trade_date="2026-06-06", selected_analysts=["market"]))
    decision = PortfolioDecisionService(config={"alpaca_use_paper": True, "trade_lifecycle_default_notional": 500}).decide(
        research.report,
        PortfolioContext(current_symbol_position="NEUTRAL", account_snapshot={"equity": 10000, "buying_power": 10000}),
    )

    assert research.report.audit_refs["run_id"] == "run-v2"
    assert decision.alpaca_intent == "CONDITIONAL_ORDER"
    assert decision.conditional_trade_plan is not None

    plan = ConditionalTradePlan(**decision.conditional_trade_plan)
    execution = ExecutionService(config={"alpaca_use_paper": True}).validate(
        plan,
        MarketObservation(symbol="NVDA", price=1000.0, gap_pct=0.01),
        account_snapshot={"equity": 10000, "buying_power": 10000},
        current_position="NEUTRAL",
    )

    assert execution.status == "needs_review"
    assert execution.broker_response is None

    evaluate_research_report(research.report, ledger=ledger)
    evaluate_investment_decision(decision, report=research.report, ledger=ledger)
    evaluate_execution_result(execution, ledger=ledger)

    records = ledger.list_layer_evaluation_records()
    assert {record["layer"] for record in records} == {"research", "decision", "execution"}
    assert {record["target_type"] for record in records} == {
        "research_report",
        "investment_decision",
        "execution_validation",
    }

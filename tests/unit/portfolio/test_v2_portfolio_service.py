from __future__ import annotations

from tradingagents.contracts import PortfolioContext, ResearchReport, ResearchRequest
from tradingagents.portfolio.service import PortfolioDecisionService


def _report(*, conclusion="B", confidence="medium"):
    request = ResearchRequest(symbol="NVDA", trade_date="2026-06-06")
    return ResearchReport(
        request_id=request.request_id,
        symbol=request.symbol,
        trade_date=request.trade_date,
        horizon=request.horizon,
        thesis="AI capex demand supports growth.",
        conclusion=conclusion,
        confidence=confidence,
        kill_conditions=["Thesis fails if AI capex slows."],
    )


def test_portfolio_decision_emits_plan_but_not_broker_authorization():
    decision = PortfolioDecisionService(config={"alpaca_use_paper": True}).decide(
        _report(),
        PortfolioContext(current_symbol_position="NEUTRAL", account_snapshot={"equity": 10000, "buying_power": 10000}),
    )

    assert decision.human_action == "BUY"
    assert decision.actionability == "conditional"
    assert decision.alpaca_intent == "CONDITIONAL_ORDER"
    assert decision.conditional_trade_plan["symbol"] == "NVDA"
    assert decision.conditional_trade_plan["execution_policy"]["paper_only"] is True
    assert "not broker authorization" in decision.rationale


def test_portfolio_decision_blocks_long_when_position_is_short():
    decision = PortfolioDecisionService().decide(
        _report(conclusion="A", confidence="high"),
        PortfolioContext(current_symbol_position="SHORT"),
    )

    assert decision.alpaca_intent == "NO_ORDER"
    assert decision.conditional_trade_plan is None
    assert any(g.name == "position_conflict" and not g.passed for g in decision.policy_gate_results)

from __future__ import annotations

import pytest

from tradingagents.contracts import (
    ExecutionResult,
    InvestmentDecision,
    LayerEvaluationTarget,
    ResearchReport,
    ResearchRequest,
)


def test_research_request_normalizes_symbol_and_requires_analysts():
    request = ResearchRequest(symbol=" nvda ", trade_date="2026-06-06", selected_analysts=["Market", "news"])

    assert request.symbol == "NVDA"
    assert request.selected_analysts == ["market", "news"]

    with pytest.raises(ValueError):
        ResearchRequest(symbol="NVDA", trade_date="2026-06-06", selected_analysts=[])


def test_investment_decision_requires_plan_for_order_intent():
    with pytest.raises(ValueError):
        InvestmentDecision(
            report_id="rpt_1",
            symbol="NVDA",
            human_action="BUY",
            actionability="conditional",
            confidence="medium",
            invalidation={"price_below": 1.0},
            alpaca_intent="CONDITIONAL_ORDER",
        )


def test_execution_result_executed_requires_broker_response():
    with pytest.raises(ValueError):
        ExecutionResult(
            plan_id="tp_1",
            symbol="NVDA",
            status="executed",
            validation_passed=True,
        )


def test_layer_target_and_report_are_serializable():
    request = ResearchRequest(symbol="AAPL", trade_date="2026-06-06")
    report = ResearchReport(
        request_id=request.request_id,
        symbol=request.symbol,
        trade_date=request.trade_date,
        horizon=request.horizon,
        thesis="AAPL thesis",
        conclusion="B",
        confidence="medium",
    )
    target = LayerEvaluationTarget(
        layer="research",
        target_type="research_report",
        report_id=report.report_id,
        symbol=report.symbol,
        anchor_date=report.trade_date,
    )

    assert report.model_dump(mode="json")["schema_version"] == "v2"
    assert target.symbol == "AAPL"

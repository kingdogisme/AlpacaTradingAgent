from __future__ import annotations

from pathlib import Path

from tradingagents.contracts import ExecutionResult, InvestmentDecision, ResearchReport
from tradingagents.eval import (
    EpisodeLedger,
    evaluate_execution_result,
    evaluate_investment_decision,
    evaluate_research_report,
    grade_investment_decision,
    grade_research_report,
)


def _complete_report() -> ResearchReport:
    return ResearchReport(
        request_id="rrq-1",
        report_id="rpt-1",
        symbol="NVDA",
        trade_date="2026-06-06",
        horizon="position",
        thesis="AI capex supports revenue growth.",
        conclusion="B",
        confidence="medium",
        variable_map=[
            {
                "name": "revenue growth",
                "bucket": "fundamentals",
                "affected_line_item": "revenue",
            }
        ],
        evidence_ledger=[
            {
                "source_label": "fundamentals_report",
                "evidence": "Guidance supports revenue growth.",
                "variable": "revenue growth",
            }
        ],
        counter_evidence=["Valuation risk."],
        pricing_check={"checked": True},
        kill_conditions=["AI capex slows."],
        next_sources=["latest guidance"],
        markdown="## Research Report\nEvidence is sufficient.",
        audit_refs={"run_id": "run-1", "audit_path": "/tmp/run.json"},
    )


def test_research_grader_passes_complete_report_and_persists_target(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    target, record = evaluate_research_report(_complete_report(), ledger=ledger)

    assert target.target_type == "research_report"
    assert record.status == "pass"
    assert record.failure_tags == []
    assert ledger.list_layer_evaluation_targets({"report_id": "rpt-1"})[0]["layer"] == "research"
    assert ledger.list_layer_evaluation_records({"report_id": "rpt-1"})[0]["status"] == "pass"


def test_research_grader_flags_missing_evidence_as_layer_failure():
    report = _complete_report().model_copy(
        update={
            "evidence_ledger": [],
            "markdown": "",
        }
    )

    record = grade_research_report(report)

    assert record.status == "fail"
    assert "missing_evidence" in record.failure_tags
    assert "missing_markdown" in record.failure_tags


def test_decision_grader_catches_hard_gate_bypass():
    decision = InvestmentDecision(
        decision_id="dec-1",
        report_id="rpt-1",
        symbol="NVDA",
        human_action="BUY",
        actionability="conditional",
        confidence="medium",
        trigger={"type": "market"},
        invalidation={"price_below": 100.0},
        alpaca_intent="CONDITIONAL_ORDER",
        conditional_trade_plan={"plan_id": "plan-1", "symbol": "NVDA"},
        policy_gate_results=[
            {"name": "position_conflict", "passed": False, "severity": "hard", "reason": "short conflict"}
        ],
        rationale="Incorrectly bypasses a hard gate.",
    )

    record = grade_investment_decision(decision, report=_complete_report())

    assert record.status == "fail"
    assert "hard_gate_bypassed" in record.failure_tags


def test_execution_grader_persists_validation_record(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    result = ExecutionResult(
        execution_id="exe-1",
        plan_id="plan-1",
        symbol="NVDA",
        status="needs_review",
        validation_passed=True,
        reason_codes=["approved"],
        observation={"observed_at": "2026-06-06T14:30:00Z", "price": 1000.0},
        order_request={"notional": 500.0},
    )

    target, record = evaluate_execution_result(result, ledger=ledger)

    assert target.target_type == "execution_validation"
    assert record.status == "pass"
    stored = ledger.list_layer_evaluation_records({"execution_id": "exe-1"})
    assert stored[0]["target_type"] == "execution_validation"
    assert stored[0]["metrics"]["status"] == "needs_review"

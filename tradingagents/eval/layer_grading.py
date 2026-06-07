from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tradingagents.contracts import (
    ExecutionResult,
    InvestmentDecision,
    LayerEvaluationRecord,
    LayerEvaluationTarget,
    ResearchReport,
)


def research_target_from_report(report: ResearchReport) -> LayerEvaluationTarget:
    return LayerEvaluationTarget(
        target_id=f"v2:research_report:{report.report_id}",
        layer="research",
        target_type="research_report",
        run_id=report.audit_refs.get("run_id"),
        report_id=report.report_id,
        symbol=report.symbol,
        horizon=report.horizon,
        anchor_date=report.trade_date,
        audit_refs=report.audit_refs,
        metadata={
            "conclusion": report.conclusion,
            "confidence": report.confidence,
            "evidence_count": len(report.evidence_ledger),
        },
    )


def decision_target_from_decision(
    decision: InvestmentDecision,
    *,
    report: ResearchReport | None = None,
) -> LayerEvaluationTarget:
    audit_refs = dict(decision.audit_refs or {})
    if report is not None:
        audit_refs.setdefault("report_id", report.report_id)
        audit_refs.setdefault("research_audit_refs", report.audit_refs)
    return LayerEvaluationTarget(
        target_id=f"v2:investment_decision:{decision.decision_id}",
        layer="decision",
        target_type="investment_decision",
        run_id=audit_refs.get("run_id") or (report.audit_refs.get("run_id") if report else None),
        report_id=decision.report_id,
        decision_id=decision.decision_id,
        plan_id=(decision.conditional_trade_plan or {}).get("plan_id"),
        symbol=decision.symbol,
        horizon=report.horizon if report is not None else None,
        anchor_date=report.trade_date if report is not None else _date_part(decision.valid_until),
        audit_refs=audit_refs,
        metadata={
            "human_action": decision.human_action,
            "actionability": decision.actionability,
            "alpaca_intent": decision.alpaca_intent,
            "confidence": decision.confidence,
        },
    )


def execution_target_from_result(result: ExecutionResult) -> LayerEvaluationTarget:
    return LayerEvaluationTarget(
        target_id=f"v2:execution_result:{result.execution_id}",
        layer="execution",
        target_type="execution_validation",
        plan_id=result.plan_id,
        execution_id=result.execution_id,
        symbol=result.symbol,
        anchor_date=_date_part((result.observation or {}).get("observed_at")),
        audit_refs={"lifecycle_event_refs": result.lifecycle_event_refs},
        metadata={
            "status": result.status,
            "validation_passed": result.validation_passed,
            "reason_codes": result.reason_codes,
        },
    )


def grade_research_report(report: ResearchReport) -> LayerEvaluationRecord:
    tags: list[str] = []
    metrics = {
        "variable_count": len(report.variable_map),
        "evidence_count": len(report.evidence_ledger),
        "counter_evidence_count": len(report.counter_evidence),
        "kill_condition_count": len(report.kill_conditions),
        "pricing_checked": bool(report.pricing_check.checked),
        "pricing_missing_count": len(report.pricing_check.missing),
        "next_source_count": len(report.next_sources),
        "markdown_present": bool(report.markdown.strip()),
        "audit_ref_count": len(report.audit_refs),
    }
    if metrics["variable_count"] == 0:
        tags.append("missing_variable_map")
    if metrics["evidence_count"] == 0:
        tags.append("missing_evidence")
    if metrics["counter_evidence_count"] == 0:
        tags.append("missing_counter_evidence")
    if not metrics["pricing_checked"] or metrics["pricing_missing_count"]:
        tags.append("pricing_check_incomplete")
    if metrics["kill_condition_count"] == 0:
        tags.append("missing_kill_conditions")
    if not metrics["markdown_present"]:
        tags.append("missing_markdown")
    if metrics["audit_ref_count"] == 0:
        tags.append("missing_audit_refs")

    hard_failures = {"missing_evidence", "missing_markdown"}
    status = _status(tags, hard_failures=hard_failures)
    return LayerEvaluationRecord(
        evaluation_id=f"v2:research_report:{report.report_id}:contract_grader",
        target_id=f"v2:research_report:{report.report_id}",
        layer="research",
        evaluator_name="research_contract_grader",
        status=status,
        score=_score(tags, metrics, hard_failures=hard_failures),
        metrics=metrics,
        failure_tags=tags,
        reason=_reason(status, tags),
        evidence_refs=[ref for ref in (report.report_id, report.audit_refs.get("audit_path")) if ref],
    )


def grade_investment_decision(
    decision: InvestmentDecision,
    *,
    report: ResearchReport | None = None,
) -> LayerEvaluationRecord:
    tags: list[str] = []
    hard_gate_failures = [
        gate.name
        for gate in decision.policy_gate_results
        if gate.severity == "hard" and not gate.passed
    ]
    has_plan = bool(decision.conditional_trade_plan)
    actionable = decision.actionability in {"buy_now", "conditional"}
    metrics = {
        "hard_gate_failure_count": len(hard_gate_failures),
        "soft_gate_failure_count": len(
            [
                gate
                for gate in decision.policy_gate_results
                if gate.severity == "soft" and not gate.passed
            ]
        ),
        "has_plan": has_plan,
        "has_trigger": decision.trigger is not None,
        "has_invalidation": decision.invalidation is not None,
        "has_rationale": bool(decision.rationale.strip()),
        "alpaca_intent": decision.alpaca_intent,
        "actionability": decision.actionability,
    }
    if report is not None:
        metrics["report_conclusion"] = report.conclusion
        metrics["report_confidence"] = report.confidence
        if decision.report_id != report.report_id:
            tags.append("report_id_mismatch")
        if decision.symbol != report.symbol:
            tags.append("symbol_mismatch")
        if report.conclusion == "D" and actionable:
            tags.append("actionable_against_failed_research")
    if decision.alpaca_intent in {"CONDITIONAL_ORDER", "IMMEDIATE_ORDER"} and not has_plan:
        tags.append("order_intent_without_plan")
    if decision.alpaca_intent == "NO_ORDER" and has_plan:
        tags.append("plan_without_order_intent")
    if hard_gate_failures and decision.alpaca_intent != "NO_ORDER":
        tags.append("hard_gate_bypassed")
    if actionable and decision.invalidation is None:
        tags.append("actionable_without_invalidation")
    if decision.actionability == "conditional" and decision.trigger is None:
        tags.append("conditional_without_trigger")
    if not metrics["has_rationale"]:
        tags.append("missing_rationale")

    hard_failures = {
        "report_id_mismatch",
        "symbol_mismatch",
        "order_intent_without_plan",
        "hard_gate_bypassed",
        "actionable_without_invalidation",
        "actionable_against_failed_research",
    }
    status = _status(tags, hard_failures=hard_failures)
    return LayerEvaluationRecord(
        evaluation_id=f"v2:investment_decision:{decision.decision_id}:contract_grader",
        target_id=f"v2:investment_decision:{decision.decision_id}",
        layer="decision",
        evaluator_name="decision_contract_grader",
        status=status,
        score=_score(tags, metrics, hard_failures=hard_failures),
        metrics=metrics,
        failure_tags=tags,
        reason=_reason(status, tags),
        evidence_refs=[ref for ref in (decision.decision_id, decision.report_id) if ref],
    )


def grade_execution_result(result: ExecutionResult) -> LayerEvaluationRecord:
    tags: list[str] = []
    metrics = {
        "status": result.status,
        "validation_passed": result.validation_passed,
        "reason_code_count": len(result.reason_codes),
        "has_order_request": result.order_request is not None,
        "has_broker_response": result.broker_response is not None,
        "lifecycle_event_count": len(result.lifecycle_event_refs),
    }
    if not result.reason_codes:
        tags.append("missing_reason_codes")
    if result.status == "executed" and not result.broker_response:
        tags.append("executed_without_broker_response")
    if result.status == "executed" and not result.validation_passed:
        tags.append("executed_without_validation")
    if not result.validation_passed and result.order_request is not None:
        tags.append("order_request_on_failed_validation")
    if result.broker_response is not None and result.order_request is None:
        tags.append("broker_response_without_order_request")
    if result.status in {"rejected", "expired"} and result.validation_passed:
        tags.append("passed_validation_with_terminal_reject_status")

    hard_failures = {
        "executed_without_broker_response",
        "executed_without_validation",
        "order_request_on_failed_validation",
        "passed_validation_with_terminal_reject_status",
    }
    status = _status(tags, hard_failures=hard_failures)
    return LayerEvaluationRecord(
        evaluation_id=f"v2:execution_result:{result.execution_id}:contract_grader",
        target_id=f"v2:execution_result:{result.execution_id}",
        layer="execution",
        evaluator_name="execution_contract_grader",
        status=status,
        score=_score(tags, metrics, hard_failures=hard_failures),
        metrics=metrics,
        failure_tags=tags,
        reason=_reason(status, tags),
        evidence_refs=[ref for ref in (result.execution_id, result.plan_id) if ref],
    )


def evaluate_research_report(report: ResearchReport, *, ledger=None) -> tuple[LayerEvaluationTarget, LayerEvaluationRecord]:
    target = research_target_from_report(report)
    record = grade_research_report(report)
    _persist(ledger, target, record)
    return target, record


def evaluate_investment_decision(
    decision: InvestmentDecision,
    *,
    report: ResearchReport | None = None,
    ledger=None,
) -> tuple[LayerEvaluationTarget, LayerEvaluationRecord]:
    target = decision_target_from_decision(decision, report=report)
    record = grade_investment_decision(decision, report=report)
    _persist(ledger, target, record)
    return target, record


def evaluate_execution_result(result: ExecutionResult, *, ledger=None) -> tuple[LayerEvaluationTarget, LayerEvaluationRecord]:
    target = execution_target_from_result(result)
    record = grade_execution_result(result)
    _persist(ledger, target, record)
    return target, record


def _persist(ledger, target: LayerEvaluationTarget, record: LayerEvaluationRecord) -> None:
    if ledger is None:
        return
    ledger.upsert_layer_evaluation_target(target)
    ledger.upsert_layer_evaluation_record(record)


def _status(tags: list[str], *, hard_failures: set[str]) -> str:
    if any(tag in hard_failures for tag in tags):
        return "fail"
    if tags:
        return "warn"
    return "pass"


def _score(tags: list[str], metrics: dict[str, Any], *, hard_failures: set[str]) -> float:
    if any(tag in hard_failures for tag in tags):
        return 0.0
    penalty = 0.12 * len(tags)
    if metrics.get("has_rationale") is False or metrics.get("markdown_present") is False:
        penalty += 0.1
    return round(max(0.0, 1.0 - penalty), 3)


def _reason(status: str, tags: list[str]) -> str:
    if status == "pass":
        return "Layer contract checks passed."
    return "Layer contract issues: " + ", ".join(tags)


def _date_part(value: Any) -> str:
    if value:
        text = str(value)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            if len(text) >= 10:
                return text[:10]
    return datetime.now(timezone.utc).date().isoformat()

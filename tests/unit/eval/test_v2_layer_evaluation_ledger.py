from __future__ import annotations

from pathlib import Path

from tradingagents.contracts import LayerEvaluationRecord, LayerEvaluationTarget
from tradingagents.eval import EpisodeLedger, LayerEvaluationResultRecord, LayerEvaluationTargetRecord


def test_layer_evaluation_contracts_are_persisted_and_queryable(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    target = LayerEvaluationTarget(
        target_id="target-research-1",
        layer="research",
        target_type="research_report",
        run_id="run-1",
        report_id="rpt-1",
        symbol="nvda",
        horizon="position",
        anchor_date="2026-06-06",
        audit_refs={"audit_path": "/tmp/run.json"},
        metadata={"conclusion": "B"},
    )
    record = LayerEvaluationRecord(
        evaluation_id="eval-1",
        target_id=target.target_id,
        layer="research",
        evaluator_name="structure_grader",
        status="warn",
        score=0.8,
        metrics={"required_sections_present": 6},
        failure_tags=["pricing_check_incomplete"],
        reason="Pricing check is present but incomplete.",
        evidence_refs=["rpt-1"],
    )

    ledger.upsert_layer_evaluation_target(target)
    ledger.upsert_layer_evaluation_record(record)

    targets = ledger.list_layer_evaluation_targets({"layer": "research", "symbol": "NVDA"})
    records = ledger.list_layer_evaluation_records({"report_id": "rpt-1", "status": "warn"})

    assert len(targets) == 1
    assert targets[0]["target_id"] == "target-research-1"
    assert targets[0]["audit_refs"]["audit_path"] == "/tmp/run.json"
    assert targets[0]["metadata"]["conclusion"] == "B"
    assert len(records) == 1
    assert records[0]["evaluation_id"] == "eval-1"
    assert records[0]["target_type"] == "research_report"
    assert records[0]["metrics"]["required_sections_present"] == 6
    assert records[0]["failure_tags"] == ["pricing_check_incomplete"]
    assert records[0]["target_metadata"]["conclusion"] == "B"


def test_layer_evaluation_records_accept_dataclass_inputs_and_artifact_filter(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    target = LayerEvaluationTargetRecord(
        target_id="target-decision-1",
        layer="decision",
        target_type="investment_decision",
        symbol="AAPL",
        anchor_date="2026-06-06",
        decision_id="dec-1",
        report_id="rpt-1",
        metadata={"actionability": "conditional"},
    )
    record = LayerEvaluationResultRecord(
        evaluation_id="eval-2",
        target_id=target.target_id,
        layer="decision",
        evaluator_name="policy_gate_grader",
        status="pass",
        score=1.0,
    )

    ledger.upsert_layer_evaluation_target(target)
    ledger.upsert_layer_evaluation_record(record)
    ledger.upsert_layer_evaluation_record(
        LayerEvaluationResultRecord(
            evaluation_id="eval-2",
            target_id=target.target_id,
            layer="decision",
            evaluator_name="policy_gate_grader",
            status="fail",
            score=0.0,
            failure_tags=["sizing_math_error"],
        )
    )

    assert ledger.get_layer_evaluation_target("target-decision-1")["decision_id"] == "dec-1"
    targets = ledger.list_layer_evaluation_targets({"artifact_id": "dec-1"})
    records = ledger.list_layer_evaluation_records({"artifact_id": "dec-1"})

    assert [item["target_id"] for item in targets] == ["target-decision-1"]
    assert [item["evaluation_id"] for item in records] == ["eval-2"]
    assert records[0]["status"] == "fail"
    assert records[0]["failure_tags"] == ["sizing_math_error"]

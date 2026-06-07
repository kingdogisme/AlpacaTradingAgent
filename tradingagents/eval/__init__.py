"""Evaluation infrastructure for agent decisions."""

from .decision_parser import parse_decision_text
from .ledger import EpisodeLedger
from .harness import build_harness_report, build_hypothesis_report
from .models import (
    CriticRecordV1,
    DecisionRecordV1,
    EpisodeRecord,
    EvaluationOutcomeRecord,
    EvaluationTargetRecord,
    ExperimentRecordV1,
    LayerEvaluationResultRecord,
    LayerEvaluationTargetRecord,
    MemoryItemRecordV1,
    MemoryPromotionRecordV1,
    MemoryRetrievalRecordV1,
    QualityObservationRecordV1,
    QualityIndexRecordV1,
    QualityReconciliationRecordV1,
    RetrievalPackRecordV1,
    RewardRecordV1,
    RewardStatusRecordV1,
    RunIndexRecordV1,
    SourceReliabilityRecordV1,
    TraceSpanV1,
)
from .rewards import RewardResolver
from .layer_grading import (
    decision_target_from_decision,
    evaluate_execution_result,
    evaluate_investment_decision,
    evaluate_research_report,
    execution_target_from_result,
    grade_execution_result,
    grade_investment_decision,
    grade_research_report,
    research_target_from_report,
)
from .layered import LayerEvaluationRepository
from .targets import EvaluationTargetBuilder, EvaluationTargetRepository, TargetAwareRewardResolver, build_target_report


def audit_pit_run(*args, **kwargs):
    from .pit import audit_pit_run as _audit_pit_run

    return _audit_pit_run(*args, **kwargs)


def run_pit_case(*args, **kwargs):
    from .pit import run_pit_case as _run_pit_case

    return _run_pit_case(*args, **kwargs)

__all__ = [
    "CriticRecordV1",
    "DecisionRecordV1",
    "EpisodeLedger",
    "EpisodeRecord",
    "EvaluationOutcomeRecord",
    "EvaluationTargetBuilder",
    "EvaluationTargetRecord",
    "EvaluationTargetRepository",
    "ExperimentRecordV1",
    "LayerEvaluationRepository",
    "LayerEvaluationResultRecord",
    "LayerEvaluationTargetRecord",
    "MemoryItemRecordV1",
    "MemoryPromotionRecordV1",
    "MemoryRetrievalRecordV1",
    "QualityObservationRecordV1",
    "QualityIndexRecordV1",
    "QualityReconciliationRecordV1",
    "RetrievalPackRecordV1",
    "RewardRecordV1",
    "RewardStatusRecordV1",
    "RewardResolver",
    "RunIndexRecordV1",
    "SourceReliabilityRecordV1",
    "TargetAwareRewardResolver",
    "TraceSpanV1",
    "audit_pit_run",
    "build_harness_report",
    "build_hypothesis_report",
    "build_target_report",
    "decision_target_from_decision",
    "evaluate_execution_result",
    "evaluate_investment_decision",
    "evaluate_research_report",
    "execution_target_from_result",
    "grade_execution_result",
    "grade_investment_decision",
    "grade_research_report",
    "parse_decision_text",
    "research_target_from_report",
    "run_pit_case",
]

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EpisodeRecord:
    run_id: str
    symbol: str
    trade_date: str
    status: str
    config: dict[str, Any] = field(default_factory=dict)
    selected_analysts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    final_signal: str | None = None
    audit_path: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DecisionRecordV1:
    run_id: str
    stage: str
    agent_name: str
    action: str | None
    confidence: str | None
    advisory_rating: str | None
    trading_mode: str | None
    horizon: str | None
    thesis: str | None
    invalidation: str | None
    risk_budget: str | None
    position_plan: str | None
    raw_text: str
    parser_status: str
    parser_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RewardRecordV1:
    run_id: str
    reward_version: str
    holding_days: int
    raw_return: float
    benchmark_return: float | None
    alpha_return: float | None
    oracle_label: str
    classification_reward: float
    pnl_reward: float
    reward_scalar: float
    components_json: dict[str, Any]
    resolved_at: str
    data_source: str


@dataclass(frozen=True)
class RewardStatusRecordV1:
    run_id: str
    reward_version: str
    reward_status: str
    holding_days: int
    components_json: dict[str, Any]
    resolved_at: str
    data_source: str


@dataclass(frozen=True)
class TraceSpanV1:
    run_id: str
    span_id: str
    parent_span_id: str | None
    span_type: str
    agent_name: str | None
    node_name: str | None
    tool_name: str | None
    started_at: str | None
    ended_at: str | None
    status: str
    metadata_json: dict[str, Any] = field(default_factory=dict)
    artifact_ref: str | None = None


@dataclass(frozen=True)
class ExperimentRecordV1:
    run_id: str
    experiment_id: str
    config_hash: str
    prompt_version: str
    model_provider: str
    quick_model: str
    deep_model: str
    selected_analysts: list[str] = field(default_factory=list)
    memory_policy: str = "none"
    critic_version: str | None = None
    reward_version: str | None = None
    leakage_risk: str = "unknown"
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryItemRecordV1:
    memory_item_id: str
    memory_type: str
    content: str
    source: str
    status: str = "candidate"
    evidence_json: dict[str, Any] = field(default_factory=dict)
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class MemoryRetrievalRecordV1:
    run_id: str
    memory_item_id: str
    stage: str
    rank: int
    score: float | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class MemoryPromotionRecordV1:
    memory_item_id: str
    from_status: str
    to_status: str
    reason: str
    promoted_by: str
    evidence_json: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class CriticRecordV1:
    run_id: str
    critic_version: str
    failure_tags: list[str] = field(default_factory=list)
    evidence_spans: list[str] = field(default_factory=list)
    reward_snapshot: dict[str, Any] = field(default_factory=dict)
    reflection_text: str = ""
    improvement_candidates: list[str] = field(default_factory=list)
    parser_status: str = "ok"
    created_at: str | None = None


@dataclass(frozen=True)
class RunIndexRecordV1:
    index_id: str
    run_id: str
    symbol: str
    trade_date: str
    horizon: str | None
    status: str
    final_action: str | None = None
    confidence: str | None = None
    advisory_rating: str | None = None
    final_signal: str | None = None
    prompt_version: str | None = None
    config_hash: str | None = None
    model_provider: str | None = None
    quick_model: str | None = None
    deep_model: str | None = None
    selected_analysts: list[str] = field(default_factory=list)
    quality_status: str = "unknown"
    quality_pass: int = 0
    quality_warn: int = 0
    quality_fail: int = 0
    quality_unknown: int = 0
    critical_failures: list[str] = field(default_factory=list)
    stale_sources: list[str] = field(default_factory=list)
    fallback_sources: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    audit_ref: str | None = None
    audit_path: str | None = None
    decision_ref: str | None = None
    quality_index_ref: str | None = None


@dataclass(frozen=True)
class QualityIndexRecordV1:
    run_id: str
    artifact_ref: str
    tool_name: str | None = None
    agent_type: str | None = None
    source_id: str = "unknown"
    provider: str | None = None
    dataset_type: str = "unknown"
    status: str = "unknown"
    freshness: str = "unknown"
    accuracy: str = "unknown"
    completeness: str = "unknown"
    criticality: str | None = None
    flags: list[str] = field(default_factory=list)
    observed_at: str | None = None
    source_age_days: int | None = None
    fallback_from: str | None = None
    timestamp: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    output_preview: str = ""


@dataclass(frozen=True)
class RetrievalPackRecordV1:
    pack_id: str
    pack_type: str
    policy_version: str
    run_id: str | None = None
    symbol: str | None = None
    horizon: str | None = None
    token_budget: int = 4000
    source_refs: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)

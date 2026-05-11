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

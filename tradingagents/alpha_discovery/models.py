from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TIERS = ("A", "B", "C", "Rejected")
OPPORTUNITY_TYPES = ("continuation", "reversal", "volatility", "second_order", "avoid")


@dataclass
class DiscoveryBatch:
    batch_id: str
    source: str
    generated_at: str
    config_json: dict[str, Any] = field(default_factory=dict)
    status: str = "open"


@dataclass
class SourceSignal:
    candidate_id: str
    source: str
    raw_artifact_id: str
    source_timestamp: str | None = None
    mentions: int | None = None
    sentiment: str | None = None
    evidence_json: dict[str, Any] = field(default_factory=dict)
    raw_text_ref: str | None = None


@dataclass
class OpportunityCandidate:
    candidate_id: str
    batch_id: str
    ticker: str
    tier: str
    alpha_score: float
    opportunity_type: str
    direction_hint: str
    theme: str | None = None
    catalyst: str | None = None
    ttl: str | None = None
    cooldown_state: str = "eligible"
    recommended_analysts: list[str] = field(default_factory=lambda: ["market", "social", "news", "macro"])
    run_reason: str | None = None
    rejected_reason: str | None = None
    status: str = "open"
    discovered_at: str | None = None
    score_components: dict[str, Any] = field(default_factory=dict)
    source_signals: list[SourceSignal] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class Handoff:
    candidate_id: str
    run_id: str
    status: str
    executed_at: str
    ata_final_signal: str | None = None
    ata_confidence: str | None = None
    plan_id: str | None = None


@dataclass
class Outcome:
    candidate_id: str
    horizon_days: int
    raw_return: float | None
    benchmark_return: float | None
    alpha_return: float | None
    mfe: float | None
    mae: float | None
    resolved_at: str


@dataclass
class DiscoveryEvent:
    event_id: int | None
    event_time: str
    event_type: str
    batch_id: str | None = None
    candidate_id: str | None = None
    ticker: str | None = None
    source: str | None = None
    status: str = "info"
    message: str | None = None
    payload_json: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


EvaluationLayer = Literal["research", "decision", "execution", "outcome"]
LayerEvaluationStatus = Literal["pass", "warn", "fail", "not_applicable", "unknown"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class LayerEvaluationTarget(BaseModel):
    """Stable target for layer-aware evaluation."""

    schema_version: Literal["v2"] = "v2"
    target_id: str = Field(default_factory=lambda: _new_id("evt"))
    layer: EvaluationLayer
    target_type: str
    run_id: str | None = None
    report_id: str | None = None
    decision_id: str | None = None
    plan_id: str | None = None
    execution_id: str | None = None
    symbol: str
    horizon: str | None = None
    anchor_date: str
    audit_refs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_symbol(self) -> "LayerEvaluationTarget":
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        return self


class LayerEvaluationRecord(BaseModel):
    """Result of a deterministic or LLM-assisted layer grader."""

    schema_version: Literal["v2"] = "v2"
    evaluation_id: str = Field(default_factory=lambda: _new_id("evr"))
    target_id: str
    layer: EvaluationLayer
    evaluator_name: str
    status: LayerEvaluationStatus = "unknown"
    score: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    failure_tags: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

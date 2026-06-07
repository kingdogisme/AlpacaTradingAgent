from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


ResearchHorizon = Literal["swing", "position", "trend"]
ResearchConclusion = Literal["A", "B", "C", "D"]
Confidence = Literal["high", "medium", "low"]
EvidenceStrength = Literal["Direct", "Inference", "Weak", "Unchecked"]
EvidenceDirection = Literal["support", "contradiction", "mixed", "neutral"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class ResearchRequest(BaseModel):
    """Research-layer input contract.

    A request should be usable without Alpaca account credentials. Alpaca may be
    used as a market data source through dataflows, but account/position state
    belongs to the portfolio decision layer.
    """

    schema_version: Literal["v2"] = "v2"
    request_id: str = Field(default_factory=lambda: _new_id("rrq"))
    symbol: str
    trade_date: str
    horizon: ResearchHorizon = "position"
    thesis: str | None = None
    selected_analysts: list[str] = Field(
        default_factory=lambda: ["market", "fundamentals", "news", "social", "macro"]
    )
    source_policy: dict[str, Any] = Field(default_factory=dict)
    output_language: str = "zh-CN"
    config_ref: str | None = None

    @model_validator(mode="after")
    def normalize_symbol_and_analysts(self) -> "ResearchRequest":
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        self.selected_analysts = [str(item).strip().lower() for item in self.selected_analysts if str(item).strip()]
        if not self.selected_analysts:
            raise ValueError("selected_analysts must not be empty")
        return self


class ResearchVariable(BaseModel):
    name: str
    bucket: str
    affected_line_item: str
    why_it_matters: str = ""
    verification_need: str = ""


class EvidenceItem(BaseModel):
    source_label: str
    source_url: str | None = None
    evidence: str
    direction: EvidenceDirection = "neutral"
    variable: str
    strength: EvidenceStrength = "Unchecked"
    audit_ref: str | None = None


class PricingCheck(BaseModel):
    checked: bool = False
    stock_performance: str | None = None
    valuation: str | None = None
    consensus_or_guidance: str | None = None
    expectation_gap: str | None = None
    missing: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Research-layer output contract.

    This is a thesis-quality report, not a broker instruction.
    """

    schema_version: Literal["v2"] = "v2"
    report_id: str = Field(default_factory=lambda: _new_id("rpt"))
    request_id: str
    symbol: str
    trade_date: str
    horizon: ResearchHorizon
    thesis: str
    conclusion: ResearchConclusion
    confidence: Confidence
    variable_map: list[ResearchVariable] = Field(default_factory=list)
    evidence_ledger: list[EvidenceItem] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    pricing_check: PricingCheck = Field(default_factory=PricingCheck)
    kill_conditions: list[str] = Field(default_factory=list)
    next_sources: list[str] = Field(default_factory=list)
    markdown: str = ""
    audit_refs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_report(self) -> "ResearchReport":
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        if not str(self.thesis or "").strip():
            raise ValueError("thesis is required")
        return self

"""Structured output schemas for decision agents.

Executable Alpaca actions remain BUY/HOLD/SELL or LONG/NEUTRAL/SHORT.
The upstream 5-tier rating is advisory metadata only.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class AdvisoryRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class ExecutableAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    LONG = "LONG"
    NEUTRAL = "NEUTRAL"
    SHORT = "SHORT"


class ResearchPlan(BaseModel):
    recommendation: ExecutableAction = Field(description="Executable action for the trader.")
    confidence: str = Field(description="Confidence level: high, medium, or low.")
    advisory_rating: Optional[AdvisoryRating] = Field(default=None, description="Optional 5-tier advisory rating.")
    rationale: str = Field(description="Evidence-backed rationale from the bull/bear debate.")
    strategic_actions: str = Field(description="Concrete trading instructions and risk considerations.")
    time_horizon: Optional[str] = Field(default=None, description="Expected holding horizon for the plan.")
    thesis: Optional[str] = Field(default=None, description="Core investment or trend thesis.")
    invalidation: Optional[str] = Field(default=None, description="Conditions that invalidate the thesis.")
    review_cadence: Optional[str] = Field(default=None, description="How often the thesis should be reviewed.")
    position_plan: Optional[str] = Field(default=None, description="Build, add, trim, or exit plan.")
    risk_budget: Optional[str] = Field(default=None, description="Risk or exposure budget for the plan.")


class TraderProposal(BaseModel):
    action: ExecutableAction = Field(description="Executable transaction action.")
    confidence: str = Field(description="Confidence level: high, medium, or low.")
    reasoning: str = Field(description="Concise reasoning anchored in the analysis packet.")
    entry_price: Optional[str] = Field(default=None, description="Entry guidance or price range.")
    stop_loss: Optional[str] = Field(default=None, description="Stop or invalidation guidance.")
    targets: Optional[str] = Field(default=None, description="Profit targets.")
    position_sizing: Optional[str] = Field(default=None, description="Position sizing guidance.")
    advisory_rating: Optional[AdvisoryRating] = Field(default=None, description="Optional 5-tier advisory rating.")
    time_horizon: Optional[str] = Field(default=None, description="Expected holding horizon.")
    thesis: Optional[str] = Field(default=None, description="Core trade or trend thesis.")
    invalidation: Optional[str] = Field(default=None, description="Thesis invalidation conditions.")
    review_cadence: Optional[str] = Field(default=None, description="Review cadence for maintaining the position.")
    position_plan: Optional[str] = Field(default=None, description="Initial allocation plus add, trim, or exit rules.")
    risk_budget: Optional[str] = Field(default=None, description="Maximum risk or exposure budget.")


class RiskDecision(BaseModel):
    action: ExecutableAction = Field(description="Final executable action for Alpaca.")
    confidence: str = Field(description="Confidence level: high, medium, or low.")
    risk_rationale: str = Field(description="Risk-adjusted justification.")
    required_controls: str = Field(description="Stops, invalidation, sizing, and risk controls.")
    advisory_rating: Optional[AdvisoryRating] = Field(default=None, description="Optional 5-tier advisory rating.")
    time_horizon: Optional[str] = Field(default=None, description="Expected holding horizon.")
    thesis: Optional[str] = Field(default=None, description="Risk-adjusted thesis.")
    invalidation: Optional[str] = Field(default=None, description="Thesis invalidation conditions.")
    review_cadence: Optional[str] = Field(default=None, description="Required review cadence.")
    position_plan: Optional[str] = Field(default=None, description="Approved build, add, trim, or exit plan.")
    risk_budget: Optional[str] = Field(default=None, description="Maximum risk or exposure budget.")


def _rating_line(rating: Optional[AdvisoryRating]) -> list[str]:
    return ["", f"**Advisory Rating**: {rating.value}"] if rating else []


def render_research_plan(plan: ResearchPlan) -> str:
    parts = [
        f"**Recommendation**: {plan.recommendation.value}",
        f"**Confidence**: {plan.confidence}",
        *_rating_line(plan.advisory_rating),
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ]
    _append_horizon_fields(parts, plan)
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{plan.recommendation.value}**"])
    return "\n".join(parts)


def render_trader_proposal(proposal: TraderProposal) -> str:
    parts = [
        f"**Action**: {proposal.action.value}",
        f"**Confidence**: {proposal.confidence}",
        *_rating_line(proposal.advisory_rating),
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price:
        parts.extend(["", f"**Entry**: {proposal.entry_price}"])
    if proposal.stop_loss:
        parts.extend(["", f"**Stop / Invalidation**: {proposal.stop_loss}"])
    if proposal.targets:
        parts.extend(["", f"**Targets**: {proposal.targets}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    _append_horizon_fields(parts, proposal)
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value}**"])
    return "\n".join(parts)


def render_risk_decision(decision: RiskDecision) -> str:
    parts = [
        f"**Action**: {decision.action.value}",
        f"**Confidence**: {decision.confidence}",
        *_rating_line(decision.advisory_rating),
        "",
        f"**Risk Rationale**: {decision.risk_rationale}",
        "",
        f"**Required Controls**: {decision.required_controls}",
    ]
    _append_horizon_fields(parts, decision)
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{decision.action.value}**"])
    return "\n".join(parts)


def _append_horizon_fields(parts: list[str], model: Any) -> None:
    optional_fields = [
        ("time_horizon", "Time Horizon"),
        ("thesis", "Thesis"),
        ("invalidation", "Invalidation"),
        ("review_cadence", "Review Cadence"),
        ("position_plan", "Position Plan"),
        ("risk_budget", "Risk Budget"),
    ]
    for field_name, label in optional_fields:
        value = getattr(model, field_name, None)
        if value:
            parts.extend(["", f"**{label}**: {value}"])

"""Structured output schemas for decision agents.

Executable Alpaca actions remain BUY/HOLD/SELL or LONG/NEUTRAL/SHORT.
The upstream 5-tier rating is advisory metadata only.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class AdvisoryRating(str, Enum):
    STRONG_BUY = "STRONG BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG SELL"


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
    advisory_rating: Optional[AdvisoryRating] = Field(
        default=None,
        description=(
            "Optional advisory-only 5-tier rating: STRONG BUY, BUY, HOLD, SELL, or STRONG SELL. "
            "This is not the executable action."
        ),
    )
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
    advisory_rating: Optional[AdvisoryRating] = Field(
        default=None,
        description=(
            "Optional advisory-only 5-tier rating: STRONG BUY, BUY, HOLD, SELL, or STRONG SELL. "
            "This is not the executable action."
        ),
    )
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
    user_recommendation: Optional[str] = Field(
        default=None,
        description=(
            "User-facing portfolio guidance that may be more nuanced than the executable Alpaca action. "
            "Include whether the idea is actionable now, watchlist-only, staged entry, add/trim/exit, and why."
        ),
    )
    alpaca_action_plan: Optional[str] = Field(
        default=None,
        description=(
            "Direct Alpaca execution instruction: exact executable action token, whether to open/add/hold/close, "
            "starter notional exposure, risk-to-invalidation, and conditions that must be met before order placement."
        ),
    )
    advisory_rating: Optional[AdvisoryRating] = Field(
        default=None,
        description=(
            "Optional advisory-only 5-tier rating: STRONG BUY, BUY, HOLD, SELL, or STRONG SELL. "
            "This is not the executable action."
        ),
    )
    time_horizon: Optional[str] = Field(default=None, description="Expected holding horizon.")
    thesis: Optional[str] = Field(default=None, description="Risk-adjusted thesis.")
    invalidation: Optional[str] = Field(default=None, description="Thesis invalidation conditions.")
    review_cadence: Optional[str] = Field(default=None, description="Required review cadence.")
    position_plan: Optional[str] = Field(default=None, description="Approved build, add, trim, or exit plan.")
    risk_budget: Optional[str] = Field(default=None, description="Maximum risk or exposure budget.")


ZH_CN_LABELS = {
    "recommendation": "建议",
    "action": "操作",
    "confidence": "信心",
    "advisory_rating": "顾问评级",
    "rationale": "理由",
    "strategic_actions": "执行计划",
    "reasoning": "判断依据",
    "entry": "入场",
    "stop_invalidation": "止损 / 失效",
    "targets": "目标",
    "position_sizing": "仓位规模",
    "risk_rationale": "风险理由",
    "required_controls": "必要风控",
    "user_recommendation": "给用户的操作建议",
    "alpaca_action_plan": "给 Alpaca 的直接动作",
    "time_horizon": "时间周期",
    "thesis": "交易论点",
    "invalidation": "失效条件",
    "review_cadence": "复核节奏",
    "position_plan": "仓位计划",
    "risk_budget": "风险预算",
}


EN_LABELS = {
    "recommendation": "Recommendation",
    "action": "Action",
    "confidence": "Confidence",
    "advisory_rating": "Advisory Rating",
    "rationale": "Rationale",
    "strategic_actions": "Strategic Actions",
    "reasoning": "Reasoning",
    "entry": "Entry",
    "stop_invalidation": "Stop / Invalidation",
    "targets": "Targets",
    "position_sizing": "Position Sizing",
    "risk_rationale": "Risk Rationale",
    "required_controls": "Required Controls",
    "user_recommendation": "User Recommendation",
    "alpaca_action_plan": "Alpaca Execution Action",
    "time_horizon": "Time Horizon",
    "thesis": "Thesis",
    "invalidation": "Invalidation",
    "review_cadence": "Review Cadence",
    "position_plan": "Position Plan",
    "risk_budget": "Risk Budget",
}


def _labels(output_language: str | None = None) -> dict[str, str]:
    language = (output_language or "").strip().lower()
    if language in {"zh", "zh-cn", "chinese", "中文", "简体中文"}:
        return ZH_CN_LABELS
    return EN_LABELS


def _field_line(label_key: str, value: str, labels: dict[str, str]) -> str:
    return f"**{labels[label_key]}**: {value}"


def render_research_plan(plan: ResearchPlan, output_language: str | None = None) -> str:
    labels = _labels(output_language)
    parts = [
        _field_line("recommendation", plan.recommendation.value, labels),
        _field_line("confidence", plan.confidence, labels),
        *_rating_line(plan.advisory_rating, labels),
        "",
        _field_line("rationale", plan.rationale, labels),
        "",
        _field_line("strategic_actions", plan.strategic_actions, labels),
    ]
    _append_horizon_fields(parts, plan, labels)
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{plan.recommendation.value}**"])
    return "\n".join(parts)


def render_trader_proposal(proposal: TraderProposal, output_language: str | None = None) -> str:
    labels = _labels(output_language)
    parts = [
        _field_line("action", proposal.action.value, labels),
        _field_line("confidence", proposal.confidence, labels),
        *_rating_line(proposal.advisory_rating, labels),
        "",
        _field_line("reasoning", proposal.reasoning, labels),
    ]
    if proposal.entry_price:
        parts.extend(["", _field_line("entry", proposal.entry_price, labels)])
    if proposal.stop_loss:
        parts.extend(["", _field_line("stop_invalidation", proposal.stop_loss, labels)])
    if proposal.targets:
        parts.extend(["", _field_line("targets", proposal.targets, labels)])
    if proposal.position_sizing:
        parts.extend(["", _field_line("position_sizing", proposal.position_sizing, labels)])
    _append_horizon_fields(parts, proposal, labels)
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value}**"])
    return "\n".join(parts)


def render_risk_decision(decision: RiskDecision, output_language: str | None = None) -> str:
    labels = _labels(output_language)
    parts = [
        _field_line("action", decision.action.value, labels),
        _field_line("confidence", decision.confidence, labels),
        *_rating_line(decision.advisory_rating, labels),
    ]
    if decision.user_recommendation:
        parts.extend(["", _field_line("user_recommendation", decision.user_recommendation, labels)])
    if decision.alpaca_action_plan:
        parts.extend(["", _field_line("alpaca_action_plan", decision.alpaca_action_plan, labels)])
    parts.extend(
        [
            "",
            _field_line("risk_rationale", decision.risk_rationale, labels),
            "",
            _field_line("required_controls", decision.required_controls, labels),
        ]
    )
    _append_horizon_fields(parts, decision, labels)
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{decision.action.value}**"])
    return "\n".join(parts)


def _rating_line(rating: Optional[AdvisoryRating], labels: dict[str, str] | None = None) -> list[str]:
    if not rating:
        return []
    label_set = labels or EN_LABELS
    value = rating.value.title() if label_set is ZH_CN_LABELS else rating.value
    return ["", f"**{label_set['advisory_rating']}**: {value}"]


def _append_horizon_fields(parts: list[str], model: Any, labels: dict[str, str]) -> None:
    optional_fields = [
        ("time_horizon", "time_horizon"),
        ("thesis", "thesis"),
        ("invalidation", "invalidation"),
        ("review_cadence", "review_cadence"),
        ("position_plan", "position_plan"),
        ("risk_budget", "risk_budget"),
    ]
    for field_name, label_key in optional_fields:
        value = getattr(model, field_name, None)
        if value:
            parts.extend(["", _field_line(label_key, value, labels)])

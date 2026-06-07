from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

try:
    from tradingagents.trade_lifecycle.models import PlanLifecycleReview
except Exception:  # pragma: no cover - keeps contracts importable in partial envs
    PlanLifecycleReview = Any  # type: ignore


HumanAction = Literal["BUY", "HOLD", "SELL", "LONG", "NEUTRAL", "SHORT"]
Actionability = Literal["buy_now", "conditional", "watchlist", "no_trade"]
AlpacaIntent = Literal["NO_ORDER", "CONDITIONAL_ORDER", "IMMEDIATE_ORDER"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class PositionSnapshot(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT", "NEUTRAL"] = "NEUTRAL"
    quantity: float | None = None
    market_value: float | None = None
    avg_entry_price: float | None = None
    unrealized_pl: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_symbol(self) -> "PositionSnapshot":
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        return self


class PortfolioContext(BaseModel):
    """Portfolio decision-layer context.

    This contract is account-aware, but it is still not an execution
    authorization. Execution hard gates run later against fresh observations.
    """

    schema_version: Literal["v2"] = "v2"
    account_snapshot: dict[str, Any] = Field(default_factory=dict)
    current_positions: list[PositionSnapshot] = Field(default_factory=list)
    current_symbol_position: Literal["LONG", "SHORT", "NEUTRAL"] = "NEUTRAL"
    theme_exposures: dict[str, Any] = Field(default_factory=dict)
    policy_config: dict[str, Any] = Field(default_factory=dict)
    active_plan_reviews: list[PlanLifecycleReview] = Field(default_factory=list)


class PolicyGateResult(BaseModel):
    name: str
    passed: bool
    severity: Literal["hard", "soft"] = "hard"
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvestmentDecision(BaseModel):
    """Portfolio decision-layer output contract."""

    schema_version: Literal["v2"] = "v2"
    decision_id: str = Field(default_factory=lambda: _new_id("dec"))
    report_id: str
    symbol: str
    human_action: HumanAction
    advisory_rating: str | None = None
    actionability: Actionability
    confidence: str
    thesis_summary: str = ""
    risk_budget: dict[str, Any] = Field(default_factory=dict)
    sizing: dict[str, Any] = Field(default_factory=dict)
    trigger: dict[str, Any] | None = None
    invalidation: dict[str, Any] | None = None
    valid_until: str | None = None
    alpaca_intent: AlpacaIntent = "NO_ORDER"
    conditional_trade_plan: dict[str, Any] | None = None
    policy_gate_results: list[PolicyGateResult] = Field(default_factory=list)
    rationale: str = ""
    audit_refs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_intent_boundary(self) -> "InvestmentDecision":
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.alpaca_intent in {"CONDITIONAL_ORDER", "IMMEDIATE_ORDER"} and not self.conditional_trade_plan:
            raise ValueError("conditional_trade_plan is required when alpaca_intent creates order intent")
        if self.actionability in {"conditional", "buy_now"} and self.invalidation is None:
            raise ValueError("actionable decisions require invalidation")
        return self

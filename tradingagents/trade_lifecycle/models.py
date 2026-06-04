from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_plan_id() -> str:
    return f"tp_{uuid4().hex[:16]}"


def new_validation_id() -> str:
    return f"tv_{uuid4().hex[:16]}"


class TradePlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    NEEDS_REVIEW = "needs_review"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    EXECUTED = "executed"
    EXPIRED = "expired"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class PlanReviewStatus(str, Enum):
    NOT_MET = "not_met"
    PARTIALLY_MET = "partially_met"
    MET = "met"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class TradePlanAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    LONG = "LONG"
    NEUTRAL = "NEUTRAL"
    SHORT = "SHORT"


ACTION_TO_SIDE = {
    TradePlanAction.BUY: "buy",
    TradePlanAction.LONG: "buy",
    TradePlanAction.SELL: "sell",
    TradePlanAction.SHORT: "sell",
    TradePlanAction.HOLD: "none",
    TradePlanAction.NEUTRAL: "none",
}


ALLOWED_STATUS_TRANSITIONS: dict[TradePlanStatus, set[TradePlanStatus]] = {
    TradePlanStatus.DRAFT: {
        TradePlanStatus.ACTIVE,
        TradePlanStatus.REJECTED,
        TradePlanStatus.CANCELLED,
    },
    TradePlanStatus.ACTIVE: {
        TradePlanStatus.TRIGGERED,
        TradePlanStatus.NEEDS_REVIEW,
        TradePlanStatus.EXECUTED,
        TradePlanStatus.EXPIRED,
        TradePlanStatus.REJECTED,
        TradePlanStatus.CANCELLED,
        TradePlanStatus.SUPERSEDED,
    },
    TradePlanStatus.TRIGGERED: {
        TradePlanStatus.NEEDS_REVIEW,
        TradePlanStatus.NEEDS_RECONCILIATION,
        TradePlanStatus.EXECUTED,
        TradePlanStatus.REJECTED,
        TradePlanStatus.CANCELLED,
    },
    TradePlanStatus.NEEDS_REVIEW: {
        TradePlanStatus.NEEDS_RECONCILIATION,
        TradePlanStatus.EXECUTED,
        TradePlanStatus.REJECTED,
        TradePlanStatus.CANCELLED,
        TradePlanStatus.SUPERSEDED,
    },
    TradePlanStatus.NEEDS_RECONCILIATION: {
        TradePlanStatus.EXECUTED,
        TradePlanStatus.REJECTED,
        TradePlanStatus.CANCELLED,
    },
    TradePlanStatus.EXECUTED: set(),
    TradePlanStatus.EXPIRED: set(),
    TradePlanStatus.REJECTED: set(),
    TradePlanStatus.CANCELLED: set(),
    TradePlanStatus.SUPERSEDED: set(),
}


class TradeTrigger(BaseModel):
    type: Literal["market", "price_above", "price_below", "price_between"] = "market"
    price_above: Optional[float] = None
    price_below: Optional[float] = None
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    volume_min_ratio: Optional[float] = None
    rsi_min: Optional[float] = None
    rsi_max: Optional[float] = None
    require_price_above_sma_50: Optional[bool] = None
    require_price_above_sma_200: Optional[bool] = None
    require_reclaim_sma_50: Optional[bool] = None
    require_reclaim_sma_200: Optional[bool] = None
    debounce_observations: int = 1
    hysteresis_pct: float = 0.0
    description: str = ""
    conditions: list["TradeTrigger"] = Field(default_factory=list)
    operator: Literal["OR"] = "OR"

    @model_validator(mode="after")
    def validate_price_shape(self) -> "TradeTrigger":
        if self.conditions:
            self.operator = "OR"
            return self
        if self.type == "price_above" and self.price_above is None:
            raise ValueError("price_above trigger requires price_above")
        if self.type == "price_below" and self.price_below is None:
            raise ValueError("price_below trigger requires price_below")
        if self.type == "price_between":
            if self.price_low is None or self.price_high is None:
                raise ValueError("price_between trigger requires price_low and price_high")
            if self.price_low > self.price_high:
                raise ValueError("price_low must be <= price_high")
        if self.debounce_observations < 1:
            raise ValueError("debounce_observations must be >= 1")
        if self.hysteresis_pct < 0:
            raise ValueError("hysteresis_pct must be non-negative")
        return self


class TradeInvalidation(BaseModel):
    price_below: Optional[float] = None
    price_above: Optional[float] = None
    reason: str = ""


class TradeRiskBudget(BaseModel):
    risk_budget_pct: Optional[float] = None
    max_notional: Optional[float] = None
    max_notional_pct: Optional[float] = None
    max_gap_pct: Optional[float] = None
    min_volume_ratio: Optional[float] = None


class ExecutionPolicy(BaseModel):
    order_type: Literal["market"] = "market"
    time_in_force: Literal["day", "gtc"] = "day"
    notional: Optional[float] = None
    qty: Optional[float] = None
    paper_only: bool = True
    allow_shorts: bool = False
    idempotency_key: Optional[str] = None
    client_order_id: Optional[str] = None


class MarketObservation(BaseModel):
    symbol: str
    observed_at: str = Field(default_factory=utc_now_iso)
    price: float
    prev_close: Optional[float] = None
    gap_pct: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    rsi_14: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PlanLifecycleReview(BaseModel):
    plan_id: str
    source_run_id: Optional[str] = None
    symbol: str
    horizon: Optional[str] = None
    status: PlanReviewStatus
    plan_status: TradePlanStatus
    trigger_met: bool = False
    invalidated: bool = False
    expired: bool = False
    observation: Optional[MarketObservation] = None
    reasons: list[str] = Field(default_factory=list)
    required_action: Optional[Literal["review", "none"]] = None
    allowed_decisions: list[str] = Field(default_factory=list)
    active_plan: dict[str, Any] = Field(default_factory=dict)


class ConditionalTradePlan(BaseModel):
    plan_id: str = Field(default_factory=new_plan_id)
    symbol: str
    action: TradePlanAction
    side: Literal["buy", "sell", "none"] | None = None
    trigger: TradeTrigger
    invalidation: TradeInvalidation = Field(default_factory=TradeInvalidation)
    valid_until: str
    risk_budget: TradeRiskBudget = Field(default_factory=TradeRiskBudget)
    max_notional: Optional[float] = None
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    source_run_id: Optional[str] = None
    source_decision: str = ""
    source_audit_path: Optional[str] = None
    horizon: Optional[str] = None
    trading_mode: Optional[str] = None
    status: TradePlanStatus = TradePlanStatus.ACTIVE
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = 1

    @model_validator(mode="after")
    def fill_and_validate(self) -> "ConditionalTradePlan":
        if not str(self.valid_until or "").strip():
            raise ValueError("valid_until is required")
        _parse_dt(self.valid_until)
        if not self.side:
            self.side = ACTION_TO_SIDE[self.action]
        if self.max_notional is not None and self.max_notional <= 0:
            raise ValueError("max_notional must be positive when provided")
        if self.risk_budget.max_notional is None and self.max_notional is not None:
            self.risk_budget.max_notional = self.max_notional
        if self.execution_policy.notional is None and self.max_notional is not None:
            self.execution_policy.notional = self.max_notional
        return self

    def is_expired(self, as_of: datetime | str | None = None) -> bool:
        return _parse_dt(self.valid_until) <= _parse_dt(as_of)

    def transition_to(self, next_status: TradePlanStatus | str) -> "ConditionalTradePlan":
        target = TradePlanStatus(next_status)
        allowed = ALLOWED_STATUS_TRANSITIONS[self.status]
        if target not in allowed and target != self.status:
            raise ValueError(f"invalid trade plan status transition: {self.status.value} -> {target.value}")
        return self.model_copy(update={"status": target, "updated_at": utc_now_iso()})


class TradePlanEvent(BaseModel):
    plan_id: str
    event_type: str
    status: str = "ok"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class PreTradeValidation(BaseModel):
    validation_id: str = Field(default_factory=new_validation_id)
    plan_id: str
    symbol: str
    passed: bool
    decision: Literal["approved", "rejected", "no_order"]
    reason_code: str
    reasons: list[str] = Field(default_factory=list)
    observation: Optional[MarketObservation] = None
    execution_policy: Optional[ExecutionPolicy] = None
    created_at: str = Field(default_factory=utc_now_iso)


def _parse_dt(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

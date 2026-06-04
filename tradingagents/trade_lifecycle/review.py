from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    ConditionalTradePlan,
    MarketObservation,
    PlanLifecycleReview,
    PlanReviewStatus,
    TradePlanStatus,
)
from .monitor import _trigger_met
from .monitor import evaluate_trigger


def review_active_plan(
    plan: ConditionalTradePlan,
    observation: MarketObservation | None = None,
    *,
    as_of: datetime | str | None = None,
) -> PlanLifecycleReview:
    reasons: list[str] = []
    expired = plan.is_expired(as_of)
    invalidated = _invalidation_breached(plan, observation)
    trigger_result = evaluate_trigger(plan, observation) if observation else {"met": False, "partial": False}
    trigger_met = bool(trigger_result["met"])

    if plan.status == TradePlanStatus.SUPERSEDED:
        status = PlanReviewStatus.SUPERSEDED
        reasons.append("plan is already superseded")
    elif expired:
        status = PlanReviewStatus.EXPIRED
        reasons.append("valid_until elapsed")
    elif plan.status == TradePlanStatus.NEEDS_REVIEW:
        status = PlanReviewStatus.MET
        reasons.append("plan trigger already requires manual review")
    elif invalidated:
        status = PlanReviewStatus.INVALIDATED
        reasons.append("numeric invalidation was breached")
    elif trigger_met:
        status = PlanReviewStatus.MET
        reasons.append("entry trigger is met")
    elif observation and (trigger_result.get("partial") or _price_trigger_met_without_confirmations(plan, observation)):
        status = PlanReviewStatus.PARTIALLY_MET
        reasons.append("price trigger is met but one or more confirmation requirements are missing")
    else:
        status = PlanReviewStatus.NOT_MET
        if observation:
            reasons.append("entry trigger is not met")
        else:
            reasons.append("no market observation was available; trigger status is unknown/not_met")

    required_action = "review" if status in {PlanReviewStatus.MET, PlanReviewStatus.PARTIALLY_MET} else "none"
    allowed = ["execute", "resize", "cancel", "supersede"] if required_action == "review" else []
    return PlanLifecycleReview(
        plan_id=plan.plan_id,
        source_run_id=plan.source_run_id,
        symbol=plan.symbol,
        horizon=plan.horizon,
        status=status,
        plan_status=plan.status,
        trigger_met=trigger_met,
        invalidated=invalidated,
        expired=expired,
        observation=observation,
        reasons=reasons,
        required_action=required_action,
        allowed_decisions=allowed,
        active_plan=plan.model_dump(mode="json"),
    )


def render_plan_review_context(reviews: list[PlanLifecycleReview]) -> str:
    if not reviews:
        return "No active conditional trade plan is currently registered for this ticker/horizon."

    lines = ["Active Conditional Trade Plan Review:"]
    for review in reviews:
        trigger = review.active_plan.get("trigger") or {}
        invalidation = review.active_plan.get("invalidation") or {}
        lines.extend(
            [
                f"- plan_id: {review.plan_id}",
                f"  source_run_id: {review.source_run_id or 'unknown'}",
                f"  lifecycle_status: {review.status.value}",
                f"  broker_plan_status: {review.plan_status.value}",
                f"  trigger: {_compact_json(trigger)}",
                f"  invalidation: {_compact_json(invalidation)}",
                f"  valid_until: {review.active_plan.get('valid_until') or 'unknown'}",
                f"  required_action: {review.required_action or 'none'}",
                f"  allowed_trigger_review_decisions: {', '.join(review.allowed_decisions) if review.allowed_decisions else 'none'}",
                f"  reasons: {'; '.join(review.reasons)}",
            ]
        )
        if review.observation:
            lines.append(
                "  observation: "
                f"price={review.observation.price}, volume_ratio={review.observation.volume_ratio}, "
                f"observed_at={review.observation.observed_at}"
            )
    return "\n".join(lines)


def latest_active_plan_review_context(
    symbol: str,
    *,
    config: dict[str, Any] | None = None,
    horizon: str | None = None,
    observation: MarketObservation | None = None,
) -> tuple[list[PlanLifecycleReview], str]:
    from .repository import TradePlanRepository

    repository = TradePlanRepository((config or {}).get("trade_lifecycle_db_path"))
    plans = repository.list_active_plans([symbol])
    if horizon:
        plans = [plan for plan in plans if not plan.horizon or str(plan.horizon).lower() == str(horizon).lower()]
    reviews = [review_active_plan(plan, observation, as_of=datetime.now(timezone.utc)) for plan in plans]
    return reviews, render_plan_review_context(reviews)


def _invalidation_breached(plan: ConditionalTradePlan, observation: MarketObservation | None) -> bool:
    if not observation:
        return False
    invalidation = plan.invalidation
    if invalidation.price_below is not None and observation.price <= invalidation.price_below:
        return True
    if invalidation.price_above is not None and observation.price >= invalidation.price_above:
        return True
    return False


def _price_trigger_met_without_confirmations(plan: ConditionalTradePlan, observation: MarketObservation) -> bool:
    trigger = plan.trigger
    if trigger.conditions:
        return any(
            _single_price_trigger_met_without_confirmations(leg, observation)
            for leg in trigger.conditions
        )
    return _single_price_trigger_met_without_confirmations(trigger, observation)


def _single_price_trigger_met_without_confirmations(trigger, observation: MarketObservation) -> bool:
    price = observation.price
    hysteresis = max(trigger.hysteresis_pct or 0.0, 0.0)
    if trigger.type == "market":
        return True
    if trigger.type == "price_above":
        return price >= float(trigger.price_above or 0) * (1 + hysteresis)
    if trigger.type == "price_below":
        return price <= float(trigger.price_below or 0) * (1 - hysteresis)
    low = float(trigger.price_low or 0) * (1 + hysteresis)
    high = float(trigger.price_high or 0) * (1 - hysteresis)
    return low <= price <= high


def _compact_json(value: Any) -> str:
    import json

    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

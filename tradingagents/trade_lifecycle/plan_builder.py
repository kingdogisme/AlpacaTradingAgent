from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .models import (
    ConditionalTradePlan,
    ExecutionPolicy,
    TradeInvalidation,
    TradeRiskBudget,
    TradeTrigger,
)
from .repository import TradePlanRepository


def build_plan_from_final_state(
    final_state: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    source_run_id: str | None = None,
    audit_path: str | None = None,
) -> ConditionalTradePlan | None:
    cfg = config or {}
    final_decision = str(final_state.get("final_trade_decision") or "")
    trading_mode = final_state.get("trading_mode") or cfg.get("trading_mode") or "investment"
    action = _extract_recommendation(final_decision, trading_mode)
    if not action:
        return None

    symbol = str(final_state.get("company_of_interest") or final_state.get("ticker") or "").upper()
    if not symbol:
        return None

    horizon = str(final_state.get("trading_horizon") or cfg.get("trading_horizon") or "position").lower()
    ttl_days = _ttl_days(cfg, horizon)
    valid_until = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
    current_price = _extract_first_number(
        final_decision,
        patterns=(
            r"entry[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
            r"entry_price[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
        ),
    )
    invalidation_price = _extract_first_number(
        final_decision,
        patterns=(
            r"(?:invalidation|stop)[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
            r"invalidation_price[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
        ),
    )
    notional = _extract_notional(final_decision) or float(cfg.get("trade_lifecycle_default_notional", 1000) or 1000)

    trigger = TradeTrigger(
        type="market" if current_price is None else "price_above",
        price_above=current_price,
        debounce_observations=int(cfg.get("trade_lifecycle_debounce_observations", 1) or 1),
        hysteresis_pct=float(cfg.get("trade_lifecycle_hysteresis_pct", 0.0) or 0.0),
        description="Risk-approved plan derived from final_trade_decision",
    )
    invalidation = TradeInvalidation(
        price_below=invalidation_price,
        reason="Extracted from final risk decision" if invalidation_price else "No numeric invalidation extracted",
    )
    risk_budget = TradeRiskBudget(
        max_notional=notional,
        max_notional_pct=_float_or_none(cfg.get("trade_lifecycle_max_notional_pct")),
        max_gap_pct=float(cfg.get("trade_lifecycle_max_gap_pct", 0.08) or 0.08),
        min_volume_ratio=_float_or_none(cfg.get("trade_lifecycle_min_volume_ratio")),
    )
    return ConditionalTradePlan(
        symbol=symbol,
        action=action,
        trigger=trigger,
        invalidation=invalidation,
        valid_until=valid_until,
        risk_budget=risk_budget,
        max_notional=notional,
        execution_policy=ExecutionPolicy(
            notional=notional,
            paper_only=True,
            allow_shorts=bool(cfg.get("allow_shorts", False)),
        ),
        source_run_id=source_run_id,
        source_decision=final_decision,
        source_audit_path=audit_path,
        horizon=horizon,
        trading_mode=trading_mode,
        status="active",
        metadata={
            "builder": "final_state_v1",
            "entry_extracted": current_price is not None,
            "invalidation_extracted": invalidation_price is not None,
            "major_new_information": _has_major_new_information(final_decision),
        },
    )


def persist_approved_plan(
    final_state: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    source_run_id: str | None = None,
    audit_path: str | None = None,
) -> ConditionalTradePlan | None:
    plan = build_plan_from_final_state(
        final_state,
        config=config,
        source_run_id=source_run_id,
        audit_path=audit_path,
    )
    if plan is None:
        return None

    repository = TradePlanRepository((config or {}).get("trade_lifecycle_db_path"))
    existing = repository.list_active_plans([plan.symbol])
    if existing:
        current = existing[0]
        if current.action != plan.action and not plan.metadata.get("major_new_information"):
            repository.append_event(
                plan_event(
                    current.plan_id,
                    "signal_reconciliation_conflict",
                    "New plan action conflicted with existing active plan; keeping existing plan until major new information is explicit.",
                    {
                        "new_action": plan.action.value,
                        "new_source_run_id": source_run_id,
                    },
                )
            )
            return current
        replacement = plan if plan.metadata.get("major_new_information") else _conservative_intersection(current, plan)
        repository.supersede_active_for_symbol(
            plan.symbol,
            replacement_plan_id=replacement.plan_id,
            reason="new risk-approved plan superseded previous active plan",
        )
        plan = replacement
    repository.upsert_plan(plan)
    repository.append_event(
        plan_event(
            plan.plan_id,
            "plan_approved",
            "Risk Judge approved conditional trade plan",
            {"source_run_id": source_run_id, "symbol": plan.symbol, "action": plan.action.value},
        )
    )
    return plan


def plan_event(plan_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None):
    from .models import TradePlanEvent

    return TradePlanEvent(
        plan_id=plan_id,
        event_type=event_type,
        message=message,
        payload=payload or {},
    )


def _conservative_intersection(existing: ConditionalTradePlan, new: ConditionalTradePlan) -> ConditionalTradePlan:
    if existing.action != new.action:
        return new

    trigger = new.trigger.model_copy(deep=True)
    if existing.trigger.type == new.trigger.type == "price_between":
        low_values = [v for v in (existing.trigger.price_low, new.trigger.price_low) if v is not None]
        high_values = [v for v in (existing.trigger.price_high, new.trigger.price_high) if v is not None]
        trigger.price_low = max(low_values) if low_values else None
        trigger.price_high = min(high_values) if high_values else None
    elif existing.trigger.type == new.trigger.type == "price_above":
        values = [v for v in (existing.trigger.price_above, new.trigger.price_above) if v is not None]
        trigger.price_above = max(values) if values else new.trigger.price_above
    elif existing.trigger.type == new.trigger.type == "price_below":
        values = [v for v in (existing.trigger.price_below, new.trigger.price_below) if v is not None]
        trigger.price_below = min(values) if values else new.trigger.price_below

    risk_budget = new.risk_budget.model_copy(deep=True)
    candidates = [v for v in (existing.risk_budget.max_notional, new.risk_budget.max_notional) if v is not None]
    if candidates:
        risk_budget.max_notional = min(candidates)
    pct_candidates = [
        v for v in (existing.risk_budget.max_notional_pct, new.risk_budget.max_notional_pct) if v is not None
    ]
    if pct_candidates:
        risk_budget.max_notional_pct = min(pct_candidates)

    valid_until = min(existing.valid_until, new.valid_until)
    max_notional_values = [value for value in (existing.max_notional, new.max_notional) if value is not None]
    max_notional = min(max_notional_values) if max_notional_values else None
    execution_policy = new.execution_policy.model_copy(update={"notional": max_notional})
    return new.model_copy(
        update={
            "trigger": trigger,
            "risk_budget": risk_budget,
            "valid_until": valid_until,
            "max_notional": max_notional,
            "execution_policy": execution_policy,
            "metadata": {
                **new.metadata,
                "arbitration": "conservative_intersection",
                "previous_plan_id": existing.plan_id,
            },
        }
    )


def _ttl_days(config: dict[str, Any], horizon: str) -> int:
    configured = config.get("trade_lifecycle_valid_days")
    if configured:
        return int(configured)
    return {"swing": 10, "position": 45, "trend": 90}.get(horizon, 45)


def _extract_first_number(text: str, *, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _float_or_none(match.group(1))
    return None


def _extract_notional(text: str) -> float | None:
    pct_match = re.search(r"notional[_\s-]*exposure[_\s-]*pct\s*=\s*([0-9]+(?:\.[0-9]+)?)%", text, flags=re.IGNORECASE)
    if pct_match:
        return None
    for pattern in (
        r"(?:notional|max_notional|starter)[^0-9$-]*\$([0-9,]+(?:\.[0-9]+)?)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _float_or_none(match.group(1).replace(",", ""))
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_major_new_information(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "earnings",
            "guidance",
            "regulatory",
            "sec investigation",
            "financing",
            "offering",
            "merger",
            "acquisition",
            "accident",
            "recall",
        )
    )


def _extract_recommendation(text: str, trading_mode: str | None = None) -> str | None:
    content = str(text or "").upper()
    preferred = ["LONG", "SHORT", "NEUTRAL"] if trading_mode == "trading" else ["BUY", "SELL", "HOLD"]
    fallback = ["LONG", "SHORT", "NEUTRAL", "BUY", "SELL", "HOLD"]
    for action in preferred + [item for item in fallback if item not in preferred]:
        if f"FINAL TRANSACTION PROPOSAL: **{action}**" in content:
            return action
    for action in preferred + [item for item in fallback if item not in preferred]:
        if re.search(rf"\b{action}\b", content[-300:]):
            return action
    return None

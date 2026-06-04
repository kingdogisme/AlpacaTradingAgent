from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .models import (
    ConditionalTradePlan,
    ExecutionPolicy,
    PlanReviewStatus,
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
    structured = _extract_plan_json(final_decision) or final_state.get("conditional_trade_plan")
    if isinstance(structured, dict) and structured:
        plan = _plan_from_structured(
            structured,
            final_state=final_state,
            config=cfg,
            final_decision=final_decision,
            trading_mode=trading_mode,
            source_run_id=source_run_id,
            audit_path=audit_path,
        )
        if plan is not None:
            return plan

    action_value = _extract_recommendation(final_decision, trading_mode)
    if not action_value:
        return None

    symbol = str(final_state.get("company_of_interest") or final_state.get("ticker") or "").upper()
    if not symbol:
        return None

    horizon = str(final_state.get("trading_horizon") or cfg.get("trading_horizon") or "position").lower()
    ttl_days = _ttl_days(cfg, horizon)
    valid_until = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
    trigger_price = _extract_first_number(
        final_decision,
        patterns=(
            r"entry[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
            r"entry_price[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
            r"(?:入场|触发|突破|确认)[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
        ),
    )
    invalidation_price = _extract_first_number(
        final_decision,
        patterns=(
            r"(?:invalidation|stop)[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
            r"invalidation_price[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
            r"(?:止损|失效|破位)[^0-9$-]*\$?([0-9]+(?:\.[0-9]+)?)",
        ),
    )
    notional = _extract_notional(final_decision) or float(cfg.get("trade_lifecycle_default_notional", 1000) or 1000)
    trigger = _default_trigger(
        action_value,
        trigger_price=trigger_price,
        config=cfg,
        description="Risk-approved plan derived from final_trade_decision",
    )
    invalidation = _default_invalidation(action_value, invalidation_price)
    risk_budget = TradeRiskBudget(
        max_notional=notional,
        max_notional_pct=_float_or_none(cfg.get("trade_lifecycle_max_notional_pct")),
        max_gap_pct=float(cfg.get("trade_lifecycle_max_gap_pct", 0.08) or 0.08),
        min_volume_ratio=_float_or_none(cfg.get("trade_lifecycle_min_volume_ratio")),
    )
    is_executable = _is_executable_plan(action_value)
    missing_policy = is_executable and (
        trigger.type == "market" or (invalidation.price_below is None and invalidation.price_above is None)
    )
    return ConditionalTradePlan(
        symbol=symbol,
        action=action_value,
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
        status="rejected" if missing_policy else "active",
        metadata={
            "builder": "final_state_v1",
            "entry_extracted": trigger_price is not None,
            "invalidation_extracted": invalidation_price is not None,
            "non_executable_reason": "missing_trigger_or_numeric_invalidation" if missing_policy else None,
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
    active_review = _active_plan_review(final_state)
    if active_review and active_review.get("status") in {PlanReviewStatus.MET.value, PlanReviewStatus.PARTIALLY_MET.value}:
        existing_plan_id = active_review.get("plan_id")
        existing = repository.get_plan(existing_plan_id) if existing_plan_id else None
        if existing and not _allows_supersede(final_state, plan):
            repository.append_event(
                plan_event(
                    existing.plan_id,
                    "trigger_review_required",
                    "Prior conditional trade plan trigger was met/partially met; keeping existing plan until execute/resize/cancel/supersede is explicit.",
                    {
                        "new_source_run_id": source_run_id,
                        "new_plan_action": plan.action.value,
                        "new_plan_trigger": plan.trigger.model_dump(mode="json"),
                        "review_status": active_review.get("status"),
                    },
                )
            )
            return existing

    if plan.status.value != "active":
        repository.upsert_plan(plan)
        repository.append_event(
            plan_event(
                plan.plan_id,
                "plan_rejected",
                plan.metadata.get("non_executable_reason") or "conditional trade plan is not executable",
                {"source_run_id": source_run_id, "symbol": plan.symbol, "action": plan.action.value},
            )
        )
        return plan

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


def _active_plan_review(final_state: dict[str, Any]) -> dict[str, Any] | None:
    reviews = ((final_state.get("active_plan_review") or {}).get("reviews") or [])
    if not reviews:
        return None
    for review in reviews:
        if review.get("status") in {PlanReviewStatus.MET.value, PlanReviewStatus.PARTIALLY_MET.value}:
            return review
    return reviews[0]


def _allows_supersede(final_state: dict[str, Any], plan: ConditionalTradePlan) -> bool:
    text = str(final_state.get("final_trade_decision") or "").lower()
    if plan.metadata.get("major_new_information"):
        return True
    return "supersede" in text and any(marker in text for marker in ("reason", "because", "new information", "major new"))


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


def _plan_from_structured(
    raw_plan: dict[str, Any],
    *,
    final_state: dict[str, Any],
    config: dict[str, Any],
    final_decision: str,
    trading_mode: str,
    source_run_id: str | None,
    audit_path: str | None,
) -> ConditionalTradePlan | None:
    payload = dict(raw_plan)
    symbol = str(payload.get("symbol") or final_state.get("company_of_interest") or final_state.get("ticker") or "").upper()
    action_value = str(payload.get("action") or payload.get("side") or "").upper()
    if action_value in {"BUY", "SELL", "HOLD", "LONG", "NEUTRAL", "SHORT"}:
        action = action_value
    else:
        action = _extract_recommendation(final_decision, trading_mode)
    if not symbol or not action:
        return None

    horizon = str(payload.get("horizon") or final_state.get("trading_horizon") or config.get("trading_horizon") or "position").lower()
    valid_until = payload.get("valid_until")
    if not valid_until:
        valid_until = (datetime.now(timezone.utc) + timedelta(days=_ttl_days(config, horizon))).isoformat()

    trigger = _coerce_trigger(payload.get("trigger") or payload.get("entry_policy"), action, config)
    invalidation = _coerce_invalidation(payload.get("invalidation") or payload.get("invalidation_policy"), action)
    risk_budget = _coerce_risk_budget(payload.get("risk_budget"), config)
    execution_policy_payload = payload.get("execution_policy") if isinstance(payload.get("execution_policy"), dict) else {}
    notional = (
        _float_or_none(payload.get("max_notional"))
        or _float_or_none(execution_policy_payload.get("notional"))
        or risk_budget.max_notional
        or float(config.get("trade_lifecycle_default_notional", 1000) or 1000)
    )
    if risk_budget.max_notional is None:
        risk_budget.max_notional = notional

    execution_policy = ExecutionPolicy(
        notional=_float_or_none(execution_policy_payload.get("notional")) or notional,
        qty=_float_or_none(execution_policy_payload.get("qty")),
        paper_only=True,
        allow_shorts=bool(config.get("allow_shorts", execution_policy_payload.get("allow_shorts", False))),
    )
    status = str(payload.get("status") or "active").lower()
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("builder", "structured_v1")
    metadata.setdefault("major_new_information", _has_major_new_information(final_decision))

    if _is_executable_plan(action) and (
        (trigger.type == "market" and not trigger.conditions)
        or (invalidation.price_below is None and invalidation.price_above is None)
    ):
        status = "rejected"
        metadata["non_executable_reason"] = "missing_trigger_or_numeric_invalidation"

    return ConditionalTradePlan(
        symbol=symbol,
        action=action,
        trigger=trigger,
        invalidation=invalidation,
        valid_until=str(valid_until),
        risk_budget=risk_budget,
        max_notional=notional,
        execution_policy=execution_policy,
        source_run_id=source_run_id or payload.get("source_run_id"),
        source_decision=final_decision,
        source_audit_path=audit_path,
        horizon=horizon,
        trading_mode=trading_mode,
        status=status,
        metadata=metadata,
    )


def _coerce_trigger(value: Any, action: str, config: dict[str, Any]) -> TradeTrigger:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    conditions = payload.get("conditions")
    if isinstance(conditions, list) and conditions:
        legs = [_coerce_trigger(_normalize_trigger_leg(condition), action, config) for condition in conditions]
        return TradeTrigger(
            type="market",
            conditions=legs,
            operator="OR",
            description=str(payload.get("description") or "OR trigger conditions"),
            debounce_observations=int(payload.get("debounce_observations") or config.get("trade_lifecycle_debounce_observations", 1) or 1),
            hysteresis_pct=float(payload.get("hysteresis_pct") or config.get("trade_lifecycle_hysteresis_pct", 0.0) or 0.0),
        )
    trigger_type = str(payload.get("type") or "").lower()
    if trigger_type not in {"market", "price_above", "price_below", "price_between"}:
        trigger_price = _float_or_none(payload.get("price") or payload.get("trigger_price"))
        if "price_low" in payload or "price_high" in payload:
            trigger_type = "price_between"
        elif trigger_price is not None:
            trigger_type = "price_below" if action == "SHORT" else "price_above"
        else:
            trigger_type = "market"
    if "price" in payload and trigger_type == "price_above":
        payload["price_above"] = payload["price"]
    if "price" in payload and trigger_type == "price_below":
        payload["price_below"] = payload["price"]
    if "trigger_price" in payload and trigger_type == "price_above":
        payload["price_above"] = payload["trigger_price"]
    if "trigger_price" in payload and trigger_type == "price_below":
        payload["price_below"] = payload["trigger_price"]
    if not payload:
        return _default_trigger(action, trigger_price=None, config=config, description="structured plan without explicit trigger")
    payload.setdefault("debounce_observations", int(config.get("trade_lifecycle_debounce_observations", 1) or 1))
    payload.setdefault("hysteresis_pct", float(config.get("trade_lifecycle_hysteresis_pct", 0.0) or 0.0))
    payload["type"] = trigger_type
    return TradeTrigger(**payload)


def _normalize_trigger_leg(condition: Any) -> dict[str, Any]:
    payload = dict(condition or {}) if isinstance(condition, dict) else {}
    normalized: dict[str, Any] = dict(payload)
    if "price_close_above" in payload and "price_above" not in normalized:
        normalized["type"] = "price_above"
        normalized["price_above"] = payload["price_close_above"]
    if "pullback_zone_low" in payload or "pullback_zone_high" in payload:
        normalized["type"] = "price_between"
        normalized.setdefault("price_low", payload.get("pullback_zone_low"))
        normalized.setdefault("price_high", payload.get("pullback_zone_high"))
    if "holds_above" in payload and "price_low" not in normalized:
        normalized.setdefault("type", "price_between")
        normalized["price_low"] = payload["holds_above"]
    volume = payload.get("volume")
    if isinstance(volume, (int, float)) and "volume_min_ratio" not in normalized:
        normalized["volume_min_ratio"] = float(volume)
    elif isinstance(volume, str) and "volume_min_ratio" not in normalized:
        if "above" in volume.lower():
            normalized["volume_min_ratio"] = 1.0
    confirmation = str(payload.get("confirmation") or "").lower()
    if "reclaim" in confirmation and "short_ma" in confirmation:
        normalized["require_reclaim_sma_50"] = True
    return normalized


def _coerce_invalidation(value: Any, action: str) -> TradeInvalidation:
    if isinstance(value, (int, float, str)):
        payload = {"price": value}
    else:
        payload = dict(value or {}) if isinstance(value, dict) else {}
    price = _float_or_none(payload.get("price") or payload.get("invalidation_price") or payload.get("stop_price"))
    if price is not None and payload.get("price_below") is None and payload.get("price_above") is None:
        if action == "SHORT":
            payload["price_above"] = price
        else:
            payload["price_below"] = price
    return TradeInvalidation(**payload)


def _coerce_risk_budget(value: Any, config: dict[str, Any]) -> TradeRiskBudget:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    if not isinstance(value, dict) and value not in (None, ""):
        payload["description"] = str(value)
    if "notional" in payload and "max_notional" not in payload:
        payload["max_notional"] = payload["notional"]
    allowed = {
        "risk_budget_pct",
        "max_notional",
        "max_notional_pct",
        "max_gap_pct",
        "min_volume_ratio",
    }
    for key in list(payload):
        if key not in allowed:
            payload.pop(key)
    budget = TradeRiskBudget(**payload)
    if budget.max_gap_pct is None:
        budget.max_gap_pct = float(config.get("trade_lifecycle_max_gap_pct", 0.08) or 0.08)
    if budget.min_volume_ratio is None:
        budget.min_volume_ratio = _float_or_none(config.get("trade_lifecycle_min_volume_ratio"))
    if budget.max_notional_pct is None:
        budget.max_notional_pct = _float_or_none(config.get("trade_lifecycle_max_notional_pct"))
    return budget


def _default_trigger(action: str, *, trigger_price: float | None, config: dict[str, Any], description: str) -> TradeTrigger:
    payload: dict[str, Any] = {
        "type": "market" if trigger_price is None else ("price_below" if action == "SHORT" else "price_above"),
        "debounce_observations": int(config.get("trade_lifecycle_debounce_observations", 1) or 1),
        "hysteresis_pct": float(config.get("trade_lifecycle_hysteresis_pct", 0.0) or 0.0),
        "description": description,
    }
    if payload["type"] == "price_below":
        payload["price_below"] = trigger_price
    elif payload["type"] == "price_above":
        payload["price_above"] = trigger_price
    return TradeTrigger(**payload)


def _default_invalidation(action: str, invalidation_price: float | None) -> TradeInvalidation:
    if action == "SHORT":
        return TradeInvalidation(
            price_above=invalidation_price,
            reason="Extracted from final risk decision" if invalidation_price else "No numeric invalidation extracted",
        )
    return TradeInvalidation(
        price_below=invalidation_price,
        reason="Extracted from final risk decision" if invalidation_price else "No numeric invalidation extracted",
    )


def _is_executable_plan(action: str) -> bool:
    return action in {"BUY", "LONG", "SELL", "SHORT"}


def _extract_first_number(text: str, *, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _float_or_none(match.group(1))
    return None


def _extract_plan_json(text: str) -> dict[str, Any] | None:
    marker = "conditional_trade_plan_json:"
    content = str(text or "")
    if marker not in content:
        return None
    raw = content.split(marker, 1)[1].lstrip()
    try:
        import json

        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
    return None


def _extract_notional(text: str) -> float | None:
    pct_match = re.search(r"notional[_\s-]*exposure[_\s-]*pct\s*=\s*([0-9]+(?:\.[0-9]+)?)%", text, flags=re.IGNORECASE)
    if pct_match:
        return None
    for pattern in (
        r"(?:notional|max_notional|starter)[^0-9$-]*\$([0-9,]+(?:\.[0-9]+)?)",
        r"(?:风险预算|仓位规模|仓位预算|名义金额|下单金额)[^0-9$-]*\$?([0-9,]+(?:\.[0-9]+)?)",
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

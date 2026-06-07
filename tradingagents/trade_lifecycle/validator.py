from __future__ import annotations

import os
from typing import Any

try:
    from tradingagents.dataflows.config import get_alpaca_use_paper
except Exception:
    get_alpaca_use_paper = None

from .models import (
    ACTION_TO_SIDE,
    ConditionalTradePlan,
    ExecutionPolicy,
    MarketObservation,
    PreTradeValidation,
    TradePlanAction,
)


NO_ORDER_ACTIONS = {TradePlanAction.HOLD, TradePlanAction.NEUTRAL}


class PreTradeValidator:
    """Lightweight pre-trade risk check for an already-approved trade plan."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def validate(
        self,
        plan: ConditionalTradePlan,
        observation: MarketObservation,
        *,
        account_info: dict[str, Any] | None = None,
        current_position: str | None = None,
    ) -> PreTradeValidation:
        reasons: list[str] = []
        reason_codes: list[str] = []

        if plan.is_expired(observation.observed_at):
            reason_codes.append("expired")
            reasons.append("stale signal: plan valid_until has elapsed")

        if not _paper_enabled(self.config):
            reason_codes.append("live_account")
            reasons.append("live account auto execution is forbidden; alpaca_use_paper must be true")

        if plan.status.value not in {"active", "needs_review", "triggered"}:
            reason_codes.append("invalid_status")
            reasons.append(f"plan status is not executable: {plan.status.value}")
        if observation.price <= 0:
            reason_codes.append("invalid_price")
            reasons.append("hard risk reject: no valid observed price")

        if plan.action in NO_ORDER_ACTIONS or plan.side == "none":
            return PreTradeValidation(
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                passed=False,
                decision="no_order",
                reason_code="no_order_action",
                reasons=["HOLD/NEUTRAL plan does not create broker orders"],
                observation=observation,
                execution_policy=None,
            )

        position_reason = self._position_reason(plan, current_position)
        if position_reason:
            code, reason, no_order = position_reason
            return PreTradeValidation(
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                passed=False,
                decision="no_order" if no_order else "rejected",
                reason_code=code,
                reasons=[reason],
                observation=observation,
                execution_policy=None,
            )

        invalidation_reason = self._invalidation_reason(plan, observation)
        if invalidation_reason:
            reason_codes.append("invalidation_breached")
            reasons.append(invalidation_reason)
        if plan.invalidation.price_below is None and plan.invalidation.price_above is None:
            reason_codes.append("missing_invalidation")
            reasons.append("hard risk reject: explicit numeric invalidation is required")

        trigger_reason = self._trigger_reason(plan, observation)
        if trigger_reason:
            reason_codes.append("trigger_not_met")
            reasons.append(trigger_reason)

        risk_reasons = self._risk_reasons(plan, observation, account_info or {})
        for code, reason in risk_reasons:
            reason_codes.append(code)
            reasons.append(reason)

        if reasons:
            return PreTradeValidation(
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                passed=False,
                decision="rejected",
                reason_code=reason_codes[0] if reason_codes else "rejected",
                reasons=reasons,
                observation=observation,
                execution_policy=None,
            )

        return PreTradeValidation(
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            passed=True,
            decision="approved",
            reason_code="approved",
            reasons=["pre-trade risk check passed"],
            observation=observation,
            execution_policy=self._execution_policy(plan, account_info or {}),
        )

    def _position_reason(
        self,
        plan: ConditionalTradePlan,
        current_position: str | None,
    ) -> tuple[str, str, bool] | None:
        position = str(current_position or "NEUTRAL").upper()
        trading_mode = str(plan.trading_mode or self.config.get("trading_mode") or "investment").lower()
        if trading_mode == "investment":
            if plan.action == TradePlanAction.SELL and position != "LONG":
                return ("flat_sell", "investment SELL requires an existing LONG position", True)
            if plan.action == TradePlanAction.BUY and position == "LONG":
                return ("already_long", "BUY plan will not add because current position is already LONG", True)
        if plan.action in {TradePlanAction.LONG, TradePlanAction.BUY} and position == "SHORT":
            return ("position_mismatch", "long-side plan cannot execute while current position is SHORT", False)
        if plan.action == TradePlanAction.SHORT:
            if "/" in plan.symbol:
                return ("crypto_short_forbidden", "crypto SHORT execution is not supported", False)
            if not bool(plan.execution_policy.allow_shorts):
                return ("shorts_disabled", "SHORT plan requires allow_shorts", False)
        return None

    def _invalidation_reason(self, plan: ConditionalTradePlan, observation: MarketObservation) -> str | None:
        invalidation = plan.invalidation
        if invalidation.price_below is not None and observation.price <= invalidation.price_below:
            return f"hard risk reject: price {observation.price:.2f} <= invalidation {invalidation.price_below:.2f}"
        if invalidation.price_above is not None and observation.price >= invalidation.price_above:
            return f"hard risk reject: price {observation.price:.2f} >= invalidation {invalidation.price_above:.2f}"
        return None

    def _trigger_reason(self, plan: ConditionalTradePlan, observation: MarketObservation) -> str | None:
        trigger = plan.trigger
        price = observation.price
        hysteresis = max(trigger.hysteresis_pct or 0.0, 0.0)

        if trigger.type == "price_above":
            threshold = float(trigger.price_above or 0) * (1 + hysteresis)
            if price < threshold:
                return f"trigger not met: price {price:.2f} < price_above {threshold:.2f}"
        elif trigger.type == "price_below":
            threshold = float(trigger.price_below or 0) * (1 - hysteresis)
            if price > threshold:
                return f"trigger not met: price {price:.2f} > price_below {threshold:.2f}"
        elif trigger.type == "price_between":
            low = float(trigger.price_low or 0) * (1 + hysteresis)
            high = float(trigger.price_high or 0) * (1 - hysteresis)
            if not (low <= price <= high):
                return f"trigger not met: price {price:.2f} outside {low:.2f}-{high:.2f}"

        if trigger.volume_min_ratio is not None and (
            observation.volume_ratio is None or observation.volume_ratio < trigger.volume_min_ratio
        ):
            return f"trigger not met: volume_ratio below {trigger.volume_min_ratio:.2f}"
        if trigger.rsi_min is not None and (observation.rsi_14 is None or observation.rsi_14 < trigger.rsi_min):
            return f"trigger not met: RSI below {trigger.rsi_min:.1f}"
        if trigger.rsi_max is not None and (observation.rsi_14 is None or observation.rsi_14 > trigger.rsi_max):
            return f"trigger not met: RSI above {trigger.rsi_max:.1f}"
        if trigger.require_price_above_sma_50 and (
            observation.sma_50 is None or observation.price <= observation.sma_50
        ):
            return "trigger not met: price is not above SMA50"
        if trigger.require_price_above_sma_200 and (
            observation.sma_200 is None or observation.price <= observation.sma_200
        ):
            return "trigger not met: price is not above SMA200"
        return None

    def _risk_reasons(
        self,
        plan: ConditionalTradePlan,
        observation: MarketObservation,
        account_info: dict[str, Any],
    ) -> list[tuple[str, str]]:
        reasons: list[tuple[str, str]] = []
        budget = plan.risk_budget
        if budget.max_gap_pct is not None and observation.gap_pct is not None:
            if abs(observation.gap_pct) > budget.max_gap_pct:
                reasons.append(
                    ("gap_risk", f"hard risk reject: gap {observation.gap_pct:.2%} exceeds {budget.max_gap_pct:.2%}")
                )
        if budget.min_volume_ratio is not None:
            if observation.volume_ratio is None or observation.volume_ratio < budget.min_volume_ratio:
                reasons.append(
                    ("liquidity", f"hard risk reject: volume_ratio below {budget.min_volume_ratio:.2f}")
                )

        equity = _safe_float(account_info.get("equity"))
        notional = self._planned_notional(plan, account_info)
        if equity and budget.max_notional_pct is not None and notional / equity > budget.max_notional_pct:
            reasons.append(
                ("max_notional_pct", f"hard risk reject: notional {notional:.2f} exceeds max_notional_pct {budget.max_notional_pct:.2%}")
            )
        buying_power = _safe_float(account_info.get("buying_power"))
        if buying_power is not None and plan.side == "buy" and notional > buying_power:
            reasons.append(
                ("buying_power", f"hard risk reject: notional {notional:.2f} exceeds buying_power {buying_power:.2f}")
            )
        if budget.max_notional is not None and notional > budget.max_notional:
            reasons.append(
                ("max_notional", f"hard risk reject: notional {notional:.2f} exceeds max_notional {budget.max_notional:.2f}")
            )

        max_single_pct = _safe_float(self.config.get("max_single_name_notional_pct"))
        if equity and max_single_pct and notional / equity > max_single_pct:
            reasons.append(
                ("single_name_cap", f"hard risk reject: notional {notional:.2f} exceeds single-name cap {max_single_pct:.2%}")
            )

        for raw_key, code, label in (
            ("theme_notional_pct", "theme_cap", "theme cap"),
            ("open_risk_pct", "open_risk_cap", "open risk cap"),
        ):
            raw_value = _safe_float(account_info.get(raw_key) or account_info.get(code))
            cap = _safe_float(self.config.get(f"max_{raw_key}") or self.config.get(f"max_{code}"))
            if raw_value is not None and cap is not None and raw_value > cap:
                reasons.append(("risk_overlay", f"hard risk reject: {label} {raw_value:.2%} exceeds {cap:.2%}"))

        return reasons

    def _execution_policy(self, plan: ConditionalTradePlan, account_info: dict[str, Any]) -> ExecutionPolicy:
        policy = plan.execution_policy.model_copy(deep=True)
        policy.paper_only = True
        policy.notional = policy.notional or self._planned_notional(plan, account_info)
        base_key = f"{plan.plan_id}:{plan.action.value}:{plan.symbol}:{policy.notional}"
        policy.idempotency_key = base_key
        policy.client_order_id = f"ata-{plan.plan_id}-{plan.action.value.lower()}-{plan.symbol.replace('/', '')}"[:48]
        if "/" in plan.symbol:
            policy.time_in_force = "gtc"
        return policy

    def _planned_notional(self, plan: ConditionalTradePlan, account_info: dict[str, Any]) -> float:
        if plan.execution_policy.notional:
            return float(plan.execution_policy.notional)
        if plan.max_notional:
            return float(plan.max_notional)
        if plan.risk_budget.max_notional:
            return float(plan.risk_budget.max_notional)
        equity = _safe_float(account_info.get("equity"))
        if equity and plan.risk_budget.max_notional_pct:
            return equity * float(plan.risk_budget.max_notional_pct)
        default_notional = self.config.get("trade_lifecycle_default_notional", self.config.get("trade_amount", 1000))
        return float(default_notional or 1000)


def execute_validated_plan(
    plan: ConditionalTradePlan,
    validation: PreTradeValidation,
    *,
    config: dict[str, Any] | None = None,
    current_position: str | None = None,
    broker_name: str | None = None,
    broker: Any | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    if not validation.passed or validation.execution_policy is None:
        return {"success": False, "error": "validation did not approve execution"}
    if validation.execution_policy.paper_only and not _paper_enabled(config):
        return {"success": False, "error": "paper-only execution blocked because Alpaca is not in paper mode"}
    policy = validation.execution_policy
    side = ACTION_TO_SIDE[plan.action]
    if side == "none":
        return {"success": True, "actions": [{"action": "hold", "message": "no broker order for HOLD/NEUTRAL plan"}]}

    if broker is None:
        from tradingagents.execution import create_broker_router

        broker = create_broker_router(config or {})
    if current_position is None and hasattr(broker, "get_current_position"):
        current_position = broker.get_current_position(plan.symbol, broker_name=broker_name)
    broker_kwargs = {
        "symbol": plan.symbol,
        "current_position": current_position or "NEUTRAL",
        "signal": plan.action.value,
        "dollar_amount": float(policy.notional or plan.max_notional or 1000),
        "allow_shorts": bool(policy.allow_shorts),
    }
    if dry_run is not None:
        broker_kwargs["dry_run"] = dry_run
    if broker_name and hasattr(broker, "resolve_broker_name"):
        broker_kwargs["broker_name"] = broker_name
    result = broker.execute_trading_action(
        **broker_kwargs,
    )
    result["client_order_id"] = policy.client_order_id
    result["idempotency_key"] = policy.idempotency_key
    return result


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _paper_enabled(config: dict[str, Any] | None = None) -> bool:
    raw = (config or {}).get("alpaca_use_paper")
    runtime_raw = os.getenv("ALPACA_USE_PAPER")
    if raw is None and get_alpaca_use_paper is not None:
        try:
            runtime_raw = get_alpaca_use_paper()
        except Exception:
            pass
    if str(runtime_raw).strip().lower() in {"0", "false", "no", "off"}:
        return False
    if raw is None:
        raw = runtime_raw if runtime_raw not in (None, "") else True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}

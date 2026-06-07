from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingagents.contracts import ExecutionResult
from tradingagents.trade_lifecycle.models import ConditionalTradePlan, MarketObservation
from tradingagents.trade_lifecycle.validator import PreTradeValidator

from .broker import BrokerAdapter, create_broker_router


@dataclass
class ExecutionService:
    """V2 Execution Layer façade around trade lifecycle validation."""

    config: dict[str, Any] | None = None
    broker: BrokerAdapter | None = None

    def validate(
        self,
        plan: ConditionalTradePlan,
        observation: MarketObservation,
        *,
        account_snapshot: dict[str, Any] | None = None,
        current_position: str | None = None,
    ) -> ExecutionResult:
        validation = PreTradeValidator(self.config or {}).validate(
            plan,
            observation,
            account_info=account_snapshot or {},
            current_position=current_position,
        )
        status = "needs_review" if validation.passed else _status_from_reason(validation.reason_code)
        return ExecutionResult(
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            status=status,
            validation_passed=validation.passed,
            reason_codes=[validation.reason_code],
            observation=observation.model_dump(mode="json"),
            account_snapshot=account_snapshot or {},
            order_request=validation.execution_policy.model_dump(mode="json") if validation.execution_policy else None,
            broker_response=None,
            lifecycle_event_refs=[],
        )

    def execute(
        self,
        plan: ConditionalTradePlan,
        observation: MarketObservation,
        *,
        account_snapshot: dict[str, Any] | None = None,
        current_position: str | None = None,
        broker_name: str | None = None,
        dry_run: bool | None = None,
    ) -> ExecutionResult:
        owns_broker = self.broker is None
        broker = self.broker or create_broker_router(self.config or {})
        effective_dry_run = True if dry_run is None and owns_broker else dry_run
        broker_error: str | None = None
        if account_snapshot is None and hasattr(broker, "get_account_snapshot"):
            try:
                account_snapshot = broker.get_account_snapshot(
                    broker_name=broker_name,
                    symbol=plan.symbol,
                )
            except ValueError as exc:
                broker_error = str(exc)
                account_snapshot = {}
        if current_position is None and hasattr(broker, "get_current_position") and broker_error is None:
            try:
                current_position = broker.get_current_position(plan.symbol, broker_name=broker_name)
            except ValueError as exc:
                broker_error = str(exc)
                current_position = "NEUTRAL"
        validation_result = self.validate(
            plan,
            observation,
            account_snapshot=account_snapshot,
            current_position=current_position,
        )
        if not validation_result.validation_passed:
            return validation_result
        if broker is None:
            return validation_result.model_copy(
                update={
                    "status": "needs_review",
                    "reason_codes": [*validation_result.reason_codes, "broker_adapter_missing"],
                }
            )
        if broker_error:
            return validation_result.model_copy(
                update={
                    "status": "needs_review",
                    "reason_codes": [*validation_result.reason_codes, "broker_adapter_unavailable"],
                    "broker_response": {"success": False, "error": broker_error},
                }
            )
        policy = validation_result.order_request or {}
        broker_kwargs = {
            "symbol": plan.symbol,
            "current_position": current_position or "NEUTRAL",
            "signal": plan.action.value,
            "dollar_amount": float(policy.get("notional") or plan.max_notional or 1000),
            "allow_shorts": bool(policy.get("allow_shorts")),
        }
        if effective_dry_run is not None:
            broker_kwargs["dry_run"] = effective_dry_run
        if broker_name and hasattr(broker, "resolve_broker_name"):
            broker_kwargs["broker_name"] = broker_name
        response = broker.execute_trading_action(**broker_kwargs)
        if response.get("success") and response.get("dry_run"):
            return validation_result.model_copy(
                update={
                    "status": "needs_review",
                    "broker_response": response,
                    "reason_codes": [*validation_result.reason_codes, "broker_dry_run"],
                }
            )
        return validation_result.model_copy(
            update={
                "status": "executed" if response.get("success") else "rejected",
                "validation_passed": bool(response.get("success")),
                "broker_response": response,
                "reason_codes": validation_result.reason_codes if response.get("success") else [*validation_result.reason_codes, "broker_rejected"],
            }
        )


def _status_from_reason(reason_code: str) -> str:
    if reason_code == "expired":
        return "expired"
    if reason_code in {"trigger_not_met", "no_order_action"}:
        return "waiting"
    return "rejected"

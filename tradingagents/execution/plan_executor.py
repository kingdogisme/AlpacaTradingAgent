from __future__ import annotations

from typing import Any

from tradingagents.contracts import ExecutionResult
from tradingagents.trade_lifecycle.models import MarketObservation, TradePlanEvent, TradePlanStatus
from tradingagents.trade_lifecycle.repository import TradePlanRepository

from .broker import BrokerRouter, create_broker_router
from .service import ExecutionService


class TradePlanExecutionService:
    """Execute reviewed trade plans through the configured broker router."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        repository: TradePlanRepository | None = None,
        broker: BrokerRouter | None = None,
    ):
        self.config = config or {}
        self.repository = repository or TradePlanRepository(self.config.get("trade_lifecycle_db_path"))
        self.broker = broker or create_broker_router(self.config)

    def execute_plan(
        self,
        plan_id: str,
        *,
        broker_name: str | None = None,
        dry_run: bool | None = None,
        observation: MarketObservation | None = None,
        account_snapshot: dict[str, Any] | None = None,
        current_position: str | None = None,
    ) -> ExecutionResult:
        plan = self.repository.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"unknown plan_id: {plan_id}")
        if plan.status not in {TradePlanStatus.ACTIVE, TradePlanStatus.NEEDS_REVIEW, TradePlanStatus.TRIGGERED}:
            raise ValueError(f"plan is not executable from status {plan.status.value}")
        observation = observation or _observation_from_latest_event(self.repository, plan_id)
        if observation is None:
            raise ValueError("plan execution requires a recent monitor observation")
        account_snapshot = account_snapshot or self.broker.get_account_snapshot(
            broker_name=broker_name,
            symbol=plan.symbol,
        )
        current_position = current_position or self.broker.get_current_position(plan.symbol, broker_name=broker_name)
        result = ExecutionService(config=self.config, broker=self.broker).execute(
            plan,
            observation,
            account_snapshot=account_snapshot,
            current_position=current_position,
            broker_name=broker_name,
            dry_run=dry_run,
        )
        self.repository.record_execution_result(plan.plan_id, result.model_dump(mode="json"))
        if result.status == "executed":
            self.repository.update_status(
                plan.plan_id,
                TradePlanStatus.EXECUTED,
                reason="broker execution succeeded",
                payload={"execution_id": result.execution_id},
            )
        elif result.status == "rejected":
            self.repository.update_status(
                plan.plan_id,
                TradePlanStatus.REJECTED,
                reason="broker execution rejected",
                payload={"execution_id": result.execution_id, "reason_codes": result.reason_codes},
            )
        else:
            self.repository.force_status(
                plan.plan_id,
                TradePlanStatus.NEEDS_REVIEW,
                reason="broker execution requires review",
                payload={"execution_id": result.execution_id, "reason_codes": result.reason_codes},
            )
        return result


def _observation_from_latest_event(repository: TradePlanRepository, plan_id: str) -> MarketObservation | None:
    for event in reversed(repository.list_events(plan_id)):
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            continue
        candidate = payload.get("observation") if "observation" in payload else payload
        if isinstance(candidate, dict) and candidate.get("symbol") and candidate.get("price") is not None:
            try:
                return MarketObservation(**candidate)
            except Exception:
                continue
    return None

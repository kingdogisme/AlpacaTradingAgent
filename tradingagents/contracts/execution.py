from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


ExecutionStatus = Literal["waiting", "needs_review", "rejected", "executed", "expired"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class ExecutionResult(BaseModel):
    """Execution-layer output contract.

    ExecutionResult records what the deterministic lifecycle/validator/broker
    boundary did. It must not reinterpret the original thesis.
    """

    schema_version: Literal["v2"] = "v2"
    execution_id: str = Field(default_factory=lambda: _new_id("exe"))
    plan_id: str
    symbol: str
    status: ExecutionStatus
    validation_passed: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    observation: dict[str, Any] = Field(default_factory=dict)
    account_snapshot: dict[str, Any] = Field(default_factory=dict)
    order_request: dict[str, Any] | None = None
    broker_response: dict[str, Any] | None = None
    lifecycle_event_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_and_check(self) -> "ExecutionResult":
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.status == "executed" and not self.validation_passed:
            raise ValueError("executed status requires validation_passed=True")
        if self.status == "executed" and not self.broker_response:
            raise ValueError("executed status requires broker_response")
        return self

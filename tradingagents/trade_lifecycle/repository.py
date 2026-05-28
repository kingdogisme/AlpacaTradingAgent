from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any, Iterable

from tradingagents.default_config import DEFAULT_CONFIG

from .models import (
    ConditionalTradePlan,
    PreTradeValidation,
    TradePlanEvent,
    TradePlanStatus,
    utc_now_iso,
)


def default_trade_lifecycle_path() -> Path:
    return Path(
        DEFAULT_CONFIG.get(
            "trade_lifecycle_db_path",
            "~/.tradingagents/trade_lifecycle/trade_lifecycle.sqlite",
        )
    ).expanduser()


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, ensure_ascii=False)


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class TradePlanRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else default_trade_lifecycle_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trade_plans (
                    plan_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_json TEXT NOT NULL,
                    invalidation_json TEXT NOT NULL,
                    risk_budget_json TEXT NOT NULL,
                    execution_policy_json TEXT NOT NULL,
                    max_notional REAL,
                    valid_until TEXT NOT NULL,
                    source_run_id TEXT,
                    source_decision TEXT NOT NULL,
                    source_audit_path TEXT,
                    horizon TEXT,
                    trading_mode TEXT,
                    metadata_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trade_plans_symbol_status
                    ON trade_plans(symbol, status);
                CREATE INDEX IF NOT EXISTS idx_trade_plans_status_valid_until
                    ON trade_plans(status, valid_until);
                CREATE INDEX IF NOT EXISTS idx_trade_plans_source_run
                    ON trade_plans(source_run_id);

                CREATE TABLE IF NOT EXISTS trade_plan_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES trade_plans(plan_id)
                );
                CREATE INDEX IF NOT EXISTS idx_trade_plan_events_plan_time
                    ON trade_plan_events(plan_id, created_at);

                CREATE TABLE IF NOT EXISTS trade_plan_validations (
                    validation_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    observation_json TEXT NOT NULL,
                    execution_policy_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES trade_plans(plan_id)
                );
                CREATE INDEX IF NOT EXISTS idx_trade_plan_validations_plan_time
                    ON trade_plan_validations(plan_id, created_at);
                """
            )

    def upsert_plan(self, plan: ConditionalTradePlan) -> ConditionalTradePlan:
        now = utc_now_iso()
        if not plan.created_at:
            plan.created_at = now
        plan.updated_at = now
        data = _model_dump(plan)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_plans (
                    plan_id, symbol, action, side, status, trigger_json, invalidation_json,
                    risk_budget_json, execution_policy_json, max_notional, valid_until,
                    source_run_id, source_decision, source_audit_path, horizon, trading_mode,
                    metadata_json, version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    action=excluded.action,
                    side=excluded.side,
                    status=excluded.status,
                    trigger_json=excluded.trigger_json,
                    invalidation_json=excluded.invalidation_json,
                    risk_budget_json=excluded.risk_budget_json,
                    execution_policy_json=excluded.execution_policy_json,
                    max_notional=excluded.max_notional,
                    valid_until=excluded.valid_until,
                    source_run_id=excluded.source_run_id,
                    source_decision=excluded.source_decision,
                    source_audit_path=excluded.source_audit_path,
                    horizon=excluded.horizon,
                    trading_mode=excluded.trading_mode,
                    metadata_json=excluded.metadata_json,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (
                    plan.plan_id,
                    plan.symbol.upper(),
                    plan.action.value,
                    plan.side,
                    plan.status.value,
                    _json_dump(data["trigger"]),
                    _json_dump(data["invalidation"]),
                    _json_dump(data["risk_budget"]),
                    _json_dump(data["execution_policy"]),
                    plan.max_notional,
                    plan.valid_until,
                    plan.source_run_id,
                    plan.source_decision,
                    plan.source_audit_path,
                    plan.horizon,
                    plan.trading_mode,
                    _json_dump(plan.metadata),
                    plan.version,
                    plan.created_at,
                    plan.updated_at,
                ),
            )
        return plan

    def get_plan(self, plan_id: str) -> ConditionalTradePlan | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        return self._row_to_plan(row) if row else None

    def list_active_plans(self, symbols: Iterable[str] | None = None) -> list[ConditionalTradePlan]:
        params: list[Any] = [TradePlanStatus.ACTIVE.value]
        where = "status = ?"
        if symbols:
            normalized = [str(symbol).upper() for symbol in symbols]
            placeholders = ",".join("?" for _ in normalized)
            where += f" AND symbol IN ({placeholders})"
            params.extend(normalized)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM trade_plans WHERE {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_plan(row) for row in rows]

    def update_status(
        self,
        plan_id: str,
        status: TradePlanStatus | str,
        *,
        reason: str = "",
        payload: dict[str, Any] | None = None,
    ) -> ConditionalTradePlan | None:
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        next_plan = plan.transition_to(status)
        self.upsert_plan(next_plan)
        self.append_event(
            TradePlanEvent(
                plan_id=plan_id,
                event_type="status_change",
                message=reason or f"{plan.status.value} -> {next_plan.status.value}",
                payload={"from": plan.status.value, "to": next_plan.status.value, **(payload or {})},
            )
        )
        return next_plan

    def expire_stale_plans(self, as_of: str | None = None) -> list[ConditionalTradePlan]:
        expired: list[ConditionalTradePlan] = []
        for plan in self.list_active_plans():
            if plan.is_expired(as_of):
                updated = self.update_status(plan.plan_id, TradePlanStatus.EXPIRED, reason="valid_until elapsed")
                if updated:
                    expired.append(updated)
        return expired

    def supersede_active_for_symbol(
        self,
        symbol: str,
        *,
        replacement_plan_id: str,
        reason: str,
    ) -> list[ConditionalTradePlan]:
        superseded: list[ConditionalTradePlan] = []
        for plan in self.list_active_plans([symbol]):
            if plan.plan_id == replacement_plan_id:
                continue
            updated = self.update_status(
                plan.plan_id,
                TradePlanStatus.SUPERSEDED,
                reason=reason,
                payload={"replacement_plan_id": replacement_plan_id},
            )
            if updated:
                superseded.append(updated)
        return superseded

    def append_event(self, event: TradePlanEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_plan_events (
                    plan_id, event_type, status, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.plan_id,
                    event.event_type,
                    event.status,
                    event.message,
                    _json_dump(event.payload),
                    event.created_at,
                ),
            )

    def record_validation(self, validation: PreTradeValidation) -> None:
        data = _model_dump(validation)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_plan_validations (
                    validation_id, plan_id, symbol, passed, decision, reasons_json,
                    observation_json, execution_policy_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validation.validation_id,
                    validation.plan_id,
                    validation.symbol.upper(),
                    1 if validation.passed else 0,
                    validation.decision,
                    _json_dump(validation.reasons),
                    _json_dump(data.get("observation") or {}),
                    _json_dump(data.get("execution_policy") or {}),
                    validation.created_at,
                ),
            )
        self.append_event(
            TradePlanEvent(
                plan_id=validation.plan_id,
                event_type="validation",
                status="passed" if validation.passed else "rejected",
                message="; ".join(validation.reasons),
                payload=data,
            )
        )

    def list_events(self, plan_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trade_plan_events WHERE plan_id = ? ORDER BY created_at ASC, event_id ASC",
                (plan_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "plan_id": row["plan_id"],
                "event_type": row["event_type"],
                "status": row["status"],
                "message": row["message"],
                "payload": _json_load(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _row_to_plan(self, row: sqlite3.Row) -> ConditionalTradePlan:
        return ConditionalTradePlan(
            plan_id=row["plan_id"],
            symbol=row["symbol"],
            action=row["action"],
            side=row["side"],
            status=row["status"],
            trigger=_json_load(row["trigger_json"], {}),
            invalidation=_json_load(row["invalidation_json"], {}),
            risk_budget=_json_load(row["risk_budget_json"], {}),
            execution_policy=_json_load(row["execution_policy_json"], {}),
            max_notional=row["max_notional"],
            valid_until=row["valid_until"],
            source_run_id=row["source_run_id"],
            source_decision=row["source_decision"],
            source_audit_path=row["source_audit_path"],
            horizon=row["horizon"],
            trading_mode=row["trading_mode"],
            metadata=_json_load(row["metadata_json"], {}),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from .ledger_records import json_dump as _json_dump, json_load as _json_load
from .models import LayerEvaluationResultRecord, LayerEvaluationTargetRecord


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LayerEvaluationRepository:
    """Persistence for ATA V2 layer-aware evaluation records.

    These records are intentionally separate from legacy directional reward
    targets. V2 graders need to diagnose whether a failure came from research,
    portfolio decisioning, execution, or delayed market outcome.
    """

    def __init__(self, ledger):
        self.ledger = ledger

    def upsert_target(self, target: LayerEvaluationTargetRecord | Any) -> None:
        record = _normalize_target(target)
        now = utc_now_iso()
        created_at = record.created_at or now
        updated_at = record.updated_at or now
        with self.ledger._connect() as conn:
            conn.execute(
                """
                INSERT INTO layer_evaluation_targets (
                    target_id, schema_version, layer, target_type, run_id,
                    report_id, decision_id, plan_id, execution_id, symbol,
                    horizon, anchor_date, audit_refs_json, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    layer=excluded.layer,
                    target_type=excluded.target_type,
                    run_id=excluded.run_id,
                    report_id=excluded.report_id,
                    decision_id=excluded.decision_id,
                    plan_id=excluded.plan_id,
                    execution_id=excluded.execution_id,
                    symbol=excluded.symbol,
                    horizon=excluded.horizon,
                    anchor_date=excluded.anchor_date,
                    audit_refs_json=excluded.audit_refs_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.target_id,
                    record.schema_version,
                    record.layer,
                    record.target_type,
                    record.run_id,
                    record.report_id,
                    record.decision_id,
                    record.plan_id,
                    record.execution_id,
                    record.symbol.upper(),
                    record.horizon,
                    record.anchor_date,
                    _json_dump(record.audit_refs),
                    _json_dump(record.metadata),
                    created_at,
                    updated_at,
                ),
            )

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        with self.ledger._connect() as conn:
            row = conn.execute(
                "SELECT * FROM layer_evaluation_targets WHERE target_id = ?",
                (target_id,),
            ).fetchone()
        return _target_from_row(row) if row else None

    def list_targets(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for key in (
            "target_id",
            "layer",
            "target_type",
            "run_id",
            "report_id",
            "decision_id",
            "plan_id",
            "execution_id",
            "symbol",
            "horizon",
        ):
            if filters.get(key):
                clauses.append(f"t.{key} = ?")
                value = filters[key]
                params.append(str(value).upper() if key == "symbol" else value)
        if filters.get("artifact_id"):
            clauses.append(
                """
                (
                    t.target_id = ?
                    OR t.report_id = ?
                    OR t.decision_id = ?
                    OR t.plan_id = ?
                    OR t.execution_id = ?
                )
                """
            )
            params.extend([filters["artifact_id"]] * 5)
        if filters.get("since"):
            clauses.append("t.anchor_date >= ?")
            params.append(filters["since"])
        if filters.get("until"):
            clauses.append("t.anchor_date <= ?")
            params.append(filters["until"])
        query = "SELECT t.* FROM layer_evaluation_targets t"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY t.anchor_date ASC, t.layer ASC, t.target_type ASC, t.symbol ASC"
        if filters.get("limit") is not None:
            query += " LIMIT ?"
            params.append(int(filters["limit"]))
        with self.ledger._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_target_from_row(row) for row in rows]

    def upsert_record(self, record: LayerEvaluationResultRecord | Any) -> None:
        item = _normalize_record(record)
        now = utc_now_iso()
        created_at = item.created_at or now
        updated_at = item.updated_at or now
        with self.ledger._connect() as conn:
            conn.execute(
                """
                INSERT INTO layer_evaluation_records (
                    evaluation_id, schema_version, target_id, layer,
                    evaluator_name, status, score, metrics_json,
                    failure_tags_json, reason, evidence_refs_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    target_id=excluded.target_id,
                    layer=excluded.layer,
                    evaluator_name=excluded.evaluator_name,
                    status=excluded.status,
                    score=excluded.score,
                    metrics_json=excluded.metrics_json,
                    failure_tags_json=excluded.failure_tags_json,
                    reason=excluded.reason,
                    evidence_refs_json=excluded.evidence_refs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    item.evaluation_id,
                    item.schema_version,
                    item.target_id,
                    item.layer,
                    item.evaluator_name,
                    item.status,
                    item.score,
                    _json_dump(item.metrics),
                    _json_dump(item.failure_tags),
                    item.reason,
                    _json_dump(item.evidence_refs),
                    created_at,
                    updated_at,
                ),
            )

    def list_records(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("evaluation_id", "target_id", "layer", "evaluator_name", "status"):
            if filters.get(key):
                clauses.append(f"r.{key} = ?")
                params.append(filters[key])
        for key in ("target_type", "run_id", "report_id", "decision_id", "plan_id", "execution_id", "symbol", "horizon"):
            if filters.get(key):
                clauses.append(f"t.{key} = ?")
                value = filters[key]
                params.append(str(value).upper() if key == "symbol" else value)
        if filters.get("artifact_id"):
            clauses.append(
                """
                (
                    t.target_id = ?
                    OR t.report_id = ?
                    OR t.decision_id = ?
                    OR t.plan_id = ?
                    OR t.execution_id = ?
                )
                """
            )
            params.extend([filters["artifact_id"]] * 5)
        if filters.get("since"):
            clauses.append("t.anchor_date >= ?")
            params.append(filters["since"])
        if filters.get("until"):
            clauses.append("t.anchor_date <= ?")
            params.append(filters["until"])
        query = """
            SELECT
                r.*,
                t.target_type,
                t.run_id,
                t.report_id,
                t.decision_id,
                t.plan_id,
                t.execution_id,
                t.symbol,
                t.horizon,
                t.anchor_date,
                t.audit_refs_json AS target_audit_refs_json,
                t.metadata_json AS target_metadata_json
            FROM layer_evaluation_records r
            JOIN layer_evaluation_targets t ON t.target_id = r.target_id
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY t.anchor_date ASC, r.layer ASC, r.evaluator_name ASC"
        if filters.get("limit") is not None:
            query += " LIMIT ?"
            params.append(int(filters["limit"]))
        with self.ledger._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_record_from_row(row) for row in rows]


def _normalize_target(target: LayerEvaluationTargetRecord | Any) -> LayerEvaluationTargetRecord:
    if isinstance(target, LayerEvaluationTargetRecord):
        return target
    data = _to_dict(target)
    return LayerEvaluationTargetRecord(
        target_id=str(data["target_id"]),
        schema_version=str(data.get("schema_version") or "v2"),
        layer=str(data["layer"]),
        target_type=str(data["target_type"]),
        run_id=data.get("run_id"),
        report_id=data.get("report_id"),
        decision_id=data.get("decision_id"),
        plan_id=data.get("plan_id"),
        execution_id=data.get("execution_id"),
        symbol=str(data["symbol"]).upper(),
        horizon=data.get("horizon"),
        anchor_date=str(data["anchor_date"]),
        audit_refs=dict(data.get("audit_refs") or {}),
        metadata=dict(data.get("metadata") or {}),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _normalize_record(record: LayerEvaluationResultRecord | Any) -> LayerEvaluationResultRecord:
    if isinstance(record, LayerEvaluationResultRecord):
        return record
    data = _to_dict(record)
    return LayerEvaluationResultRecord(
        evaluation_id=str(data["evaluation_id"]),
        schema_version=str(data.get("schema_version") or "v2"),
        target_id=str(data["target_id"]),
        layer=str(data["layer"]),
        evaluator_name=str(data["evaluator_name"]),
        status=str(data.get("status") or "unknown"),
        score=data.get("score"),
        metrics=dict(data.get("metrics") or {}),
        failure_tags=list(data.get("failure_tags") or []),
        reason=str(data.get("reason") or ""),
        evidence_refs=list(data.get("evidence_refs") or []),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


def _target_from_row(row) -> dict[str, Any]:
    item = dict(row)
    item["audit_refs"] = _json_load(item.pop("audit_refs_json", None), {})
    item["metadata"] = _json_load(item.pop("metadata_json", None), {})
    return item


def _record_from_row(row) -> dict[str, Any]:
    item = dict(row)
    item["metrics"] = _json_load(item.pop("metrics_json", None), {})
    item["failure_tags"] = _json_load(item.pop("failure_tags_json", None), [])
    item["evidence_refs"] = _json_load(item.pop("evidence_refs_json", None), [])
    item["target_audit_refs"] = _json_load(item.pop("target_audit_refs_json", None), {})
    item["target_metadata"] = _json_load(item.pop("target_metadata_json", None), {})
    return item

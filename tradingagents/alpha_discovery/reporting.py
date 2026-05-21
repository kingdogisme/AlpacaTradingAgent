from __future__ import annotations

import datetime
import json
from typing import Any


def compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    components = row.get("score_components") or {}
    return {
        "candidate_id": row.get("candidate_id"),
        "ticker": row.get("ticker"),
        "tier": row.get("tier"),
        "alpha_score": row.get("alpha_score"),
        "opportunity_type": row.get("opportunity_type"),
        "direction_hint": row.get("direction_hint"),
        "theme": row.get("theme"),
        "run_reason": row.get("run_reason"),
        "promotion_gate": components.get("promotion_gate"),
        "confirmation_sources": components.get("confirmation_sources", []),
        "risk_flags": row.get("risk_flags", []),
        "run_status": row.get("run_status"),
        "execute": row.get("execute"),
    }


def compact_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_time": row.get("event_time"),
        "event_type": row.get("event_type"),
        "status": row.get("status"),
        "batch_id": row.get("batch_id"),
        "candidate_id": row.get("candidate_id"),
        "ticker": row.get("ticker"),
        "source": row.get("source"),
        "message": row.get("message"),
        "duration_ms": row.get("duration_ms"),
        "payload": row.get("payload_json") or {},
    }


def count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def json_envelope(kind: str, payload: dict[str, Any] | list[Any]) -> str:
    envelope = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "component": "alpha_discovery",
        "kind": kind,
        "payload": payload,
    }
    return json.dumps(envelope, ensure_ascii=False, default=str)


def jsonl_event(kind: str, payload: dict[str, Any] | list[Any]) -> str:
    return json_envelope(kind, payload)

"""Trace normalization helpers for EpisodeLedger."""

from __future__ import annotations

import json
from typing import Any

TRACE_EVENT_TYPES = {
    "prompt",
    "llm_call",
    "tool_call",
    "agent_output",
    "node_execution",
    "node_error",
}

MEMORY_ITEM_TYPES = {
    "episodic",
    "semantic_candidate",
    "procedural_candidate",
    "asset_profile_candidate",
    "data_quality_candidate",
}


def _safe_span_token(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    return "".join(char if char.isalnum() else "_" for char in text).strip("_") or "unknown"


def _event_agent_name(event_type: str, payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if payload.get("agent_name"):
        return str(payload["agent_name"])
    if payload.get("agent_type"):
        return str(payload["agent_type"])
    if metadata.get("agent_name"):
        return str(metadata["agent_name"])
    report_type = payload.get("report_type") or payload.get("output_type")
    if report_type:
        return str(report_type)
    return None


def _event_node_name(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return payload.get("node_name") or metadata.get("node_name")


def _event_metadata(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "report_type",
        "output_type",
        "model",
        "purpose",
        "effort",
        "verbosity",
        "latency_seconds",
        "input_chars",
        "output_chars",
        "execution_time_seconds",
        "elapsed_seconds",
        "retry_count",
        "quality_details",
        "error_details",
        "error_message",
    ):
        if key in payload:
            metadata[key] = payload.get(key)
    if isinstance(payload.get("metadata"), dict):
        metadata["event_metadata"] = payload["metadata"]
    if event_type == "tool_call" and "inputs" in payload:
        metadata["input_keys"] = sorted((payload.get("inputs") or {}).keys())
    return metadata


def _flatten_json_lists(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    result: list[Any] = []
    for item in value:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result


def _token_estimate(value: Any) -> int:
    return max(1, len(json.dumps(value or {}, ensure_ascii=False, default=str)) // 4)

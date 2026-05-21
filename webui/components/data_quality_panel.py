from __future__ import annotations

from collections import Counter
from typing import Any

import dash_bootstrap_components as dbc
from dash import html


def _quality_from_call(call: dict[str, Any]) -> dict[str, Any]:
    quality = (call.get("quality_details") or {}).get("data_quality") or {}
    if not isinstance(quality, dict):
        return {}
    return quality


def summarize_tool_call_quality(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter()
    stale_sources: set[str] = set()
    fallback_sources: set[str] = set()
    critical_failures: set[str] = set()
    source_statuses: dict[str, dict[str, Any]] = {}

    for call in tool_calls:
        quality = _quality_from_call(call)
        if not quality:
            continue
        status = str(quality.get("status") or "unknown").lower()
        if status not in {"pass", "warn", "fail", "unknown"}:
            status = "unknown"
        counts[status] += 1
        source_id = str(quality.get("source_id") or "unknown")
        source = source_statuses.setdefault(
            source_id,
            {
                "source_id": source_id,
                "provider": quality.get("provider"),
                "dataset_type": quality.get("dataset_type"),
                "status": status,
                "flags": set(),
                "observed_at": quality.get("observed_at"),
            },
        )
        source["flags"].update(quality.get("flags") or [])
        source["status"] = _worse_status(source["status"], status)
        if quality.get("observed_at"):
            source["observed_at"] = quality.get("observed_at")
        if "stale_source" in (quality.get("flags") or []):
            stale_sources.add(source_id)
        if quality.get("fallback_from"):
            fallback_sources.add(source_id)
        if status == "fail" and quality.get("criticality") == "critical":
            critical_failures.add(source_id)

    return {
        "counts": {key: counts.get(key, 0) for key in ("pass", "warn", "fail", "unknown")},
        "stale_sources": sorted(stale_sources),
        "fallback_sources": sorted(fallback_sources),
        "critical_failures": sorted(critical_failures),
        "source_statuses": [
            {
                **value,
                "flags": sorted(value["flags"]),
            }
            for value in sorted(source_statuses.values(), key=lambda item: item["source_id"])
        ],
    }


def render_data_quality_panel(tool_calls: list[dict[str, Any]]) -> Any:
    summary = summarize_tool_call_quality(tool_calls)
    counts = summary["counts"]
    total = sum(counts.values())
    if total == 0:
        return html.Div("Data Quality: no tool evidence yet.", className="text-secondary small mt-3")

    badges = html.Div(
        [
            dbc.Badge(f"Pass {counts['pass']}", color="success", className="me-1"),
            dbc.Badge(f"Warn {counts['warn']}", color="warning", className="me-1"),
            dbc.Badge(f"Fail {counts['fail']}", color="danger", className="me-1"),
            dbc.Badge(f"Unknown {counts['unknown']}", color="secondary", className="me-1"),
        ],
        className="mb-2",
    )

    rows = []
    for source in summary["source_statuses"][:8]:
        rows.append(
            html.Tr(
                [
                    html.Td(source["source_id"]),
                    html.Td(source.get("dataset_type") or ""),
                    html.Td(_status_badge(source.get("status"))),
                    html.Td(source.get("observed_at") or "unknown"),
                    html.Td(", ".join(source.get("flags") or []) or "-"),
                ]
            )
        )

    risk_text = []
    if summary["critical_failures"]:
        risk_text.append(f"critical failures: {', '.join(summary['critical_failures'])}")
    if summary["stale_sources"]:
        risk_text.append(f"stale: {', '.join(summary['stale_sources'])}")
    if summary["fallback_sources"]:
        risk_text.append(f"fallback: {', '.join(summary['fallback_sources'])}")

    return html.Div(
        [
            html.H6("Data Quality", className="mt-3 mb-2"),
            badges,
            html.Div("; ".join(risk_text), className="text-warning small mb-2") if risk_text else None,
            dbc.Table(
                [
                    html.Thead(html.Tr([html.Th("Source"), html.Th("Type"), html.Th("Status"), html.Th("Observed"), html.Th("Flags")])),
                    html.Tbody(rows),
                ],
                bordered=True,
                hover=True,
                responsive=True,
                size="sm",
            ),
        ]
    )


def _status_badge(status: str | None) -> Any:
    status = str(status or "unknown").lower()
    color = {"pass": "success", "warn": "warning", "fail": "danger", "unknown": "secondary"}.get(status, "secondary")
    return dbc.Badge(status, color=color)


def _worse_status(left: str, right: str) -> str:
    rank = {"pass": 0, "unknown": 1, "warn": 2, "fail": 3}
    return right if rank.get(right, 1) > rank.get(left, 1) else left

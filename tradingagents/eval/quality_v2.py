from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import re
from typing import Any

from .indexing import build_quality_index
from .ledger import EpisodeLedger
from .models import (
    QualityObservationRecordV1,
    QualityReconciliationRecordV1,
    SourceReliabilityRecordV1,
)


PRICE_MISMATCH_WARN_THRESHOLD_PCT = 1.0
RELIABILITY_WINDOWS = (7, 30, 90)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_quality_observations(ledger: EpisodeLedger, run_id: str) -> list[dict[str, Any]]:
    build_quality_index(ledger, run_id)
    quality_rows = ledger.list_quality_index(run_id)
    ledger.clear_quality_observations(run_id)
    records = [_observation_from_quality(row, run_id) for row in quality_rows]
    ledger.upsert_quality_observations(records)
    return [asdict(record) for record in records]


def reconcile_quality(
    ledger: EpisodeLedger,
    run_id: str,
    *,
    price_warn_threshold_pct: float = PRICE_MISMATCH_WARN_THRESHOLD_PCT,
) -> dict[str, Any]:
    observations = build_quality_observations(ledger, run_id)
    quality_rows = ledger.list_quality_index(run_id)
    ledger.clear_quality_reconciliation(run_id)
    records: list[QualityReconciliationRecordV1] = []
    records.extend(_price_reconciliation(run_id, observations, price_warn_threshold_pct))
    records.extend(_sec_precedence(run_id, quality_rows))
    records.extend(_news_timestamp_coverage(run_id, quality_rows))
    records.extend(_macro_observation_recency(run_id, quality_rows))
    ledger.upsert_quality_reconciliation(records)
    reconciliation = ledger.list_quality_reconciliation(run_id)
    reliability = build_source_reliability(ledger)
    return {
        "generated_at": utc_now_iso(),
        "run_id": run_id,
        "summary": {
            "observations": len(observations),
            "reconciliation_checks": len(reconciliation),
            "warn": sum(1 for item in reconciliation if item.get("status") == "warn"),
            "unknown": sum(1 for item in reconciliation if item.get("status") == "unknown"),
        },
        "observations": ledger.list_quality_observations(run_id),
        "reconciliation_checks": reconciliation,
        "source_reliability": reliability,
        "artifact_refs": _artifact_refs(observations, reconciliation),
        "recommended_debug_queries": [
            f"python -m cli.main quality-index --run-id {run_id} --include-reconciliation --format json",
            f"python -m cli.main source-reliability --window-days 30 --format json",
        ],
    }


def build_source_reliability(
    ledger: EpisodeLedger,
    *,
    windows: tuple[int, ...] = RELIABILITY_WINDOWS,
) -> list[dict[str, Any]]:
    events = _all_quality_rows(ledger)
    reconciliations = _all_reconciliation_rows(ledger)
    records: list[SourceReliabilityRecordV1] = []
    for window in windows:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            grouped[(event.get("source_id") or "unknown", event.get("dataset_type") or "unknown")].append(event)
        for recon in reconciliations:
            for source_key in ("primary_source", "comparison_source"):
                source_id = recon.get(source_key)
                if source_id:
                    grouped[(source_id, recon.get("dataset_type") or "unknown")].append(
                        {
                            "status": recon.get("status"),
                            "flags": recon.get("flags") or [],
                            "criticality": "medium",
                            "fallback_from": None,
                        }
                    )
        for (source_id, dataset_type), rows in grouped.items():
            counts = Counter(row.get("status") if row.get("status") in {"pass", "warn", "fail", "unknown"} else "unknown" for row in rows)
            total = max(1, len(rows))
            fallback_count = sum(1 for row in rows if row.get("fallback_from") or "fallback_used" in (row.get("flags") or []))
            record = SourceReliabilityRecordV1(
                source_id=str(source_id),
                dataset_type=str(dataset_type),
                window_days=window,
                quality_pass=counts.get("pass", 0),
                quality_warn=counts.get("warn", 0),
                quality_fail=counts.get("fail", 0),
                quality_unknown=counts.get("unknown", 0),
                fallback_count=fallback_count,
                stale_count=sum(1 for row in rows if "stale_source" in (row.get("flags") or [])),
                critical_fail_count=sum(
                    1
                    for row in rows
                    if row.get("status") == "fail" and row.get("criticality") == "critical"
                ),
                pass_rate=counts.get("pass", 0) / total,
                fallback_rate=fallback_count / total,
                updated_at=utc_now_iso(),
            )
            records.append(record)
    ledger.upsert_source_reliability(records)
    return [asdict(record) for record in records]


def quality_index_with_reconciliation(ledger: EpisodeLedger, run_id: str) -> dict[str, Any]:
    result = reconcile_quality(ledger, run_id)
    quality_rows = ledger.list_quality_index(run_id)
    result["quality_index"] = quality_rows
    result["summary"]["quality_index_records"] = len(quality_rows)
    return result


def _observation_from_quality(row: dict[str, Any], run_id: str) -> QualityObservationRecordV1:
    dataset_type = row.get("dataset_type") or "unknown"
    observation_type = _observation_type(dataset_type, row)
    value = _extract_numeric_observation(row)
    flags = []
    status = "unknown"
    if value is not None:
        status = "pass"
    else:
        flags.append("observation_value_unparsed")
    return QualityObservationRecordV1(
        run_id=run_id,
        artifact_ref=str(row.get("artifact_ref") or "unknown"),
        symbol=row.get("symbol") or (row.get("inputs") or {}).get("symbol"),
        source_id=str(row.get("source_id") or "unknown"),
        dataset_type=str(dataset_type),
        observation_type=observation_type,
        observed_at=row.get("observed_at"),
        value_num=value,
        unit="USD" if value is not None and observation_type in {"latest_close", "latest_quote"} else None,
        extraction_status=status,
        flags=flags,
        source_ref=str(row.get("artifact_ref") or "unknown"),
    )


def _observation_type(dataset_type: str, row: dict[str, Any]) -> str:
    if dataset_type in {"price_bars", "technical_indicators"}:
        return "latest_close"
    if dataset_type == "quote":
        return "latest_quote"
    if dataset_type in {"news", "social", "macro_news"}:
        return "published_at"
    if dataset_type in {"filings", "fundamentals"}:
        return "filing_metric"
    if dataset_type == "macro":
        return "macro_observation"
    return "unknown"


def _extract_numeric_observation(row: dict[str, Any]) -> float | None:
    text = " ".join(
        str(value or "")
        for value in (
            row.get("output_preview"),
            row.get("observed_at"),
        )
    )
    patterns = [
        r"(?:latest\s+close|close|last|price|quote)\s*[:=]\s*\$?\s*(-?\d+(?:\.\d+)?)",
        r"\bclose\s+\$?\s*(-?\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _price_reconciliation(
    run_id: str,
    observations: list[dict[str, Any]],
    threshold_pct: float,
) -> list[QualityReconciliationRecordV1]:
    price_obs = [
        obs
        for obs in observations
        if obs.get("observation_type") in {"latest_close", "latest_quote"}
    ]
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in price_obs:
        by_symbol[str(obs.get("symbol") or "unknown")].append(obs)
    records = []
    for symbol, rows in by_symbol.items():
        parsed = [row for row in rows if row.get("value_num") is not None]
        if len({row.get("source_id") for row in parsed}) < 2:
            source_refs = [row.get("source_ref") for row in rows if row.get("source_ref")]
            records.append(
                QualityReconciliationRecordV1(
                    reconciliation_id=f"recon:{run_id}:{symbol}:price_latest_close_delta_pct:missing_secondary",
                    run_id=run_id,
                    symbol=symbol,
                    dataset_type="price_bars",
                    check_type="price_latest_close_delta_pct",
                    primary_source=parsed[0].get("source_id") if parsed else rows[0].get("source_id") if rows else None,
                    status="unknown",
                    severity="low",
                    flags=["missing_secondary_source"],
                    source_refs=source_refs,
                )
            )
            continue
        primary = parsed[0]
        for comparison in parsed[1:]:
            if comparison.get("source_id") == primary.get("source_id"):
                continue
            base = float(primary["value_num"])
            other = float(comparison["value_num"])
            delta_pct = abs(other - base) / abs(base) * 100 if base else None
            flags = []
            status = "pass"
            severity = "low"
            if delta_pct is not None and delta_pct > threshold_pct:
                status = "warn"
                severity = "medium"
                flags.append("cross_source_price_mismatch")
            records.append(
                QualityReconciliationRecordV1(
                    reconciliation_id=f"recon:{run_id}:{symbol}:price_latest_close_delta_pct:{primary['source_id']}:{comparison['source_id']}",
                    run_id=run_id,
                    symbol=symbol,
                    dataset_type="price_bars",
                    check_type="price_latest_close_delta_pct",
                    primary_source=primary.get("source_id"),
                    comparison_source=comparison.get("source_id"),
                    status=status,
                    severity=severity,
                    delta_pct=delta_pct,
                    flags=flags,
                    source_refs=[primary.get("source_ref"), comparison.get("source_ref")],
                )
            )
    return records


def _sec_precedence(run_id: str, rows: list[dict[str, Any]]) -> list[QualityReconciliationRecordV1]:
    has_sec = any(row.get("source_id") == "sec_edgar_fundamentals" for row in rows)
    supplementals = [
        row
        for row in rows
        if row.get("source_id") in {"finnhub_fundamentals", "alpha_vantage_fundamentals"}
    ]
    if not has_sec or not supplementals:
        return []
    return [
        QualityReconciliationRecordV1(
            reconciliation_id=f"recon:{run_id}:fundamentals:sec_precedence",
            run_id=run_id,
            symbol=(supplementals[0].get("inputs") or {}).get("symbol"),
            dataset_type="fundamentals",
            check_type="sec_precedence",
            primary_source="sec_edgar_fundamentals",
            comparison_source="supplemental_fundamentals",
            status="pass",
            severity="low",
            flags=["sec_official_facts_canonical"],
            source_refs=[row.get("artifact_ref") for row in rows if row.get("source_id") in {"sec_edgar_fundamentals", "finnhub_fundamentals", "alpha_vantage_fundamentals"}],
        )
    ]


def _news_timestamp_coverage(run_id: str, rows: list[dict[str, Any]]) -> list[QualityReconciliationRecordV1]:
    news = [row for row in rows if row.get("dataset_type") in {"news", "social", "macro_news"}]
    if not news:
        return []
    missing = [row for row in news if not row.get("observed_at") or "missing_observed_timestamp" in (row.get("flags") or [])]
    ratio = len(missing) / len(news)
    return [
        QualityReconciliationRecordV1(
            reconciliation_id=f"recon:{run_id}:news:timestamp_coverage",
            run_id=run_id,
            symbol=(news[0].get("inputs") or {}).get("symbol"),
            dataset_type="news",
            check_type="news_timestamp_coverage",
            primary_source="news_sources",
            status="warn" if ratio > 0 else "pass",
            severity="medium" if ratio > 0.5 else "low",
            delta_pct=ratio * 100,
            flags=["missing_news_timestamp"] if missing else [],
            source_refs=[row.get("artifact_ref") for row in news if row.get("artifact_ref")],
        )
    ]


def _macro_observation_recency(run_id: str, rows: list[dict[str, Any]]) -> list[QualityReconciliationRecordV1]:
    macro = [row for row in rows if row.get("dataset_type") == "macro"]
    if not macro:
        return []
    return [
        QualityReconciliationRecordV1(
            reconciliation_id=f"recon:{run_id}:macro:observation_recency",
            run_id=run_id,
            symbol=None,
            dataset_type="macro",
            check_type="macro_observation_recency",
            primary_source="macro_sources",
            status="unknown",
            severity="low",
            flags=["macro_release_observation_dates_unparsed"],
            source_refs=[row.get("artifact_ref") for row in macro if row.get("artifact_ref")],
        )
    ]


def _all_quality_rows(ledger: EpisodeLedger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:  # noqa: SLF001 - internal eval helper.
        rows = conn.execute("SELECT * FROM quality_index").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        import json

        item["flags"] = json.loads(item.pop("flags_json") or "[]")
        item["inputs"] = json.loads(item.pop("inputs_json") or "{}")
        result.append(item)
    return result


def _all_reconciliation_rows(ledger: EpisodeLedger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:  # noqa: SLF001 - internal eval helper.
        rows = conn.execute("SELECT * FROM quality_reconciliation").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        import json

        item["flags"] = json.loads(item.pop("flags_json") or "[]")
        item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
        result.append(item)
    return result


def _artifact_refs(observations: list[dict[str, Any]], reconciliation: list[dict[str, Any]]) -> list[str]:
    refs = [obs.get("source_ref") for obs in observations if obs.get("source_ref")]
    refs.extend(ref for row in reconciliation for ref in (row.get("source_refs") or []) if ref)
    return sorted({str(ref) for ref in refs})

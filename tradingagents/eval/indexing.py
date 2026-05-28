from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.dataflows.data_quality import (
    load_audit_payload,
    quality_events_from_audit,
    summarize_quality_events,
)

from .ledger import EpisodeLedger
from .models import QualityIndexRecordV1, RetrievalPackRecordV1, RunIndexRecordV1


INDEX_POLICY_VERSION = "index_v1"
RETRIEVAL_POLICY_VERSION = "retrieval_pack_v1"
QUALITY_STATUS_RANK = {"pass": 0, "unknown": 1, "warn": 2, "fail": 3}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_quality_index(ledger: EpisodeLedger, run_id: str) -> list[dict[str, Any]]:
    episode = ledger.load_episode(run_id)
    if not episode:
        return []
    audit = _load_episode_audit(episode)
    if not audit:
        ledger.clear_quality_index(run_id)
        return []

    records = [
        QualityIndexRecordV1(
            run_id=run_id,
            artifact_ref=str(event.get("artifact_ref") or "unknown"),
            tool_name=event.get("tool_name"),
            agent_type=event.get("agent_type"),
            source_id=str(event.get("source_id") or "unknown"),
            provider=event.get("provider"),
            dataset_type=str(event.get("dataset_type") or "unknown"),
            status=str(event.get("status") or "unknown"),
            freshness=str(event.get("freshness") or "unknown"),
            accuracy=str(event.get("accuracy") or "unknown"),
            completeness=str(event.get("completeness") or "unknown"),
            criticality=event.get("criticality"),
            flags=list(event.get("flags") or []),
            observed_at=event.get("observed_at"),
            source_age_days=event.get("source_age_days"),
            fallback_from=event.get("fallback_from"),
            timestamp=event.get("timestamp"),
            inputs=event.get("inputs") or {},
            output_preview=str(event.get("output_preview") or "")[:240],
        )
        for event in quality_events_from_audit(audit)
    ]
    ledger.clear_quality_index(run_id)
    ledger.upsert_quality_index(records)
    return [asdict(record) for record in records]


def build_run_index(ledger: EpisodeLedger, run_id: str) -> dict[str, Any] | None:
    episode = ledger.load_episode(run_id)
    if not episode:
        return None

    flags: list[str] = []
    audit = _load_episode_audit(episode)
    if audit:
        quality_events = quality_events_from_audit(audit)
        summary = summarize_quality_events(
            quality_events,
            run_id=episode.get("run_id"),
            symbol=episode.get("symbol"),
            trade_date=episode.get("trade_date"),
        )
        build_quality_index(ledger, run_id)
    else:
        quality_events = []
        flags.append("audit_missing")
        summary = summarize_quality_events(
            [],
            run_id=episode.get("run_id"),
            symbol=episode.get("symbol"),
            trade_date=episode.get("trade_date"),
        )

    final_decision = _final_decision(episode)
    experiment = episode.get("experiment") or {}
    config = episode.get("config") or {}
    counts = summary.get("summary") or {}
    quality_status = _worst_status([event.get("status") for event in quality_events])

    record = RunIndexRecordV1(
        index_id=f"run_index:{run_id}",
        run_id=run_id,
        symbol=str(episode.get("symbol") or "unknown"),
        trade_date=str(episode.get("trade_date") or "unknown"),
        horizon=(
            final_decision.get("horizon")
            or config.get("trading_horizon")
            or (episode.get("metadata") or {}).get("trading_horizon")
        ),
        status=str(episode.get("status") or "unknown"),
        final_action=final_decision.get("action") or episode.get("final_signal"),
        confidence=final_decision.get("confidence"),
        advisory_rating=final_decision.get("advisory_rating"),
        final_signal=episode.get("final_signal"),
        prompt_version=experiment.get("prompt_version") or str(config.get("prompt_version") or "default"),
        config_hash=experiment.get("config_hash"),
        model_provider=experiment.get("model_provider") or config.get("llm_provider"),
        quick_model=experiment.get("quick_model") or config.get("quick_think_llm"),
        deep_model=experiment.get("deep_model") or config.get("deep_think_llm"),
        selected_analysts=experiment.get("selected_analysts") or episode.get("selected_analysts") or [],
        quality_status=quality_status,
        quality_pass=int(counts.get("quality_pass", 0) or 0),
        quality_warn=int(counts.get("quality_warn", 0) or 0),
        quality_fail=int(counts.get("quality_fail", 0) or 0),
        quality_unknown=int(counts.get("quality_unknown", 0) or 0),
        critical_failures=list(counts.get("critical_failures") or []),
        stale_sources=list(counts.get("stale_sources") or []),
        fallback_sources=list(counts.get("fallback_sources") or []),
        flags=flags,
        audit_ref=f"audit:{run_id}",
        audit_path=episode.get("audit_path"),
        decision_ref=f"decision:{run_id}:final",
        quality_index_ref=f"quality_index:{run_id}",
    )
    ledger.upsert_run_index(record)
    return asdict(record)


def rebuild_run_indexes(
    ledger: EpisodeLedger,
    *,
    symbol: str | None = None,
    since: str | None = None,
    until: str | None = None,
    status: str = "completed",
) -> list[dict[str, Any]]:
    filters: dict[str, Any] = {"status": status}
    if symbol:
        filters["symbol"] = symbol
    if since:
        filters["since"] = since
    if until:
        filters["until"] = until
    records = []
    for episode in ledger.list_episodes(filters):
        record = build_run_index(ledger, episode.run_id)
        if record:
            records.append(record)
    return records


def build_retrieval_pack(
    ledger: EpisodeLedger,
    *,
    pack_type: str,
    run_id: str | None = None,
    symbol: str | None = None,
    horizon: str | None = None,
    prompt_version: str | None = None,
    config_hash: str | None = None,
    limit: int = 5,
    token_budget: int = 4000,
    include_high_leakage: bool = False,
) -> dict[str, Any]:
    if pack_type == "risk_review":
        record = _risk_review_pack(ledger, run_id=run_id, token_budget=token_budget)
    elif pack_type == "ticker_horizon":
        record = _ticker_horizon_pack(
            ledger,
            symbol=symbol,
            horizon=horizon,
            limit=limit,
            token_budget=token_budget,
            include_high_leakage=include_high_leakage,
        )
    elif pack_type == "prompt_audit":
        record = _prompt_audit_pack(
            ledger,
            prompt_version=prompt_version,
            config_hash=config_hash,
            limit=limit,
            token_budget=token_budget,
            include_high_leakage=include_high_leakage,
        )
    else:
        raise ValueError(f"Unsupported retrieval pack type: {pack_type}")

    ledger.upsert_retrieval_pack(record)
    stored = ledger.load_retrieval_pack(record.pack_id) or asdict(record)
    artifact_refs = [
        item.get("source_ref")
        for item in stored.get("items", [])
        if item.get("source_ref")
    ]
    return {
        "generated_at": utc_now_iso(),
        **stored,
        "artifact_refs": artifact_refs,
        "recommended_debug_queries": _pack_debug_queries(stored),
    }


def _risk_review_pack(
    ledger: EpisodeLedger,
    *,
    run_id: str | None,
    token_budget: int,
) -> RetrievalPackRecordV1:
    if not run_id:
        raise ValueError("risk_review pack requires run_id")
    build_run_index(ledger, run_id)
    rows = ledger.list_run_index({"run_id": run_id, "include_high_leakage": True})
    run_row = rows[0] if rows else {}
    quality_rows = ledger.list_quality_index(run_id)
    risk_rows = [
        row
        for row in quality_rows
        if row.get("status") in {"warn", "fail"} or row.get("flags")
    ][:10]
    items = [
        _pack_item(
            rank=1,
            item_type="run_summary",
            reason="Current run final decision and quality rollup.",
            source_ref=f"run_index:{run_id}",
            payload=run_row,
        )
    ]
    for idx, row in enumerate(risk_rows, start=2):
        items.append(
            _pack_item(
                rank=idx,
                item_type="quality_risk",
                reason="Warn/fail data quality event for risk review.",
                source_ref=str(row.get("artifact_ref")),
                payload=row,
            )
        )
    return RetrievalPackRecordV1(
        pack_id=f"retrieval_pack:{run_id}:risk_review:v1",
        pack_type="risk_review",
        policy_version=RETRIEVAL_POLICY_VERSION,
        run_id=run_id,
        symbol=run_row.get("symbol"),
        horizon=run_row.get("horizon"),
        token_budget=token_budget,
        source_refs=[f"run_index:{run_id}", f"quality_index:{run_id}"],
        summary={
            "run_id": run_id,
            "final_action": run_row.get("final_action"),
            "quality_status": run_row.get("quality_status"),
            "critical_failures": run_row.get("critical_failures") or [],
            "risk_items": len(risk_rows),
        },
        items=items,
    )


def _ticker_horizon_pack(
    ledger: EpisodeLedger,
    *,
    symbol: str | None,
    horizon: str | None,
    limit: int,
    token_budget: int,
    include_high_leakage: bool,
) -> RetrievalPackRecordV1:
    if not symbol or not horizon:
        raise ValueError("ticker_horizon pack requires symbol and horizon")
    rebuild_run_indexes(ledger, symbol=symbol)
    rows = ledger.list_run_index(
        {
            "symbol": symbol,
            "horizon": horizon,
            "status": "completed",
            "limit": limit,
            "include_high_leakage": include_high_leakage,
        }
    )
    items = [
        _pack_item(
            rank=idx,
            item_type="historical_run",
            reason="Recent completed run for same symbol and horizon.",
            source_ref=str(row.get("index_id") or f"run_index:{row.get('run_id')}"),
            payload=row,
        )
        for idx, row in enumerate(rows, start=1)
    ]
    return RetrievalPackRecordV1(
        pack_id=f"retrieval_pack:{symbol}:{horizon}:ticker_horizon:v1",
        pack_type="ticker_horizon",
        policy_version=RETRIEVAL_POLICY_VERSION,
        symbol=symbol,
        horizon=horizon,
        token_budget=token_budget,
        source_refs=[str(row.get("index_id")) for row in rows if row.get("index_id")],
        summary={
            "symbol": symbol,
            "horizon": horizon,
            "runs": len(rows),
            "action_distribution": dict(Counter(row.get("final_action") or "UNKNOWN" for row in rows)),
            "quality_distribution": dict(Counter(row.get("quality_status") or "unknown" for row in rows)),
        },
        items=items,
    )


def _prompt_audit_pack(
    ledger: EpisodeLedger,
    *,
    prompt_version: str | None,
    config_hash: str | None,
    limit: int,
    token_budget: int,
    include_high_leakage: bool,
) -> RetrievalPackRecordV1:
    filters: dict[str, Any] = {
        "status": "completed",
        "limit": limit,
        "include_high_leakage": include_high_leakage,
    }
    rebuild_run_indexes(ledger)
    if prompt_version:
        filters["prompt_version"] = prompt_version
    if config_hash:
        filters["config_hash"] = config_hash
    rows = ledger.list_run_index(filters)
    items = [
        _pack_item(
            rank=idx,
            item_type="prompt_run",
            reason="Completed run matching prompt/config audit filter.",
            source_ref=str(row.get("index_id") or f"run_index:{row.get('run_id')}"),
            payload=row,
        )
        for idx, row in enumerate(rows, start=1)
    ]
    rewards = [_latest_reward(ledger, row.get("run_id")) for row in rows]
    resolved_rewards = [reward for reward in rewards if reward and reward.get("reward_scalar") is not None]
    return RetrievalPackRecordV1(
        pack_id=f"retrieval_pack:prompt_audit:{prompt_version or config_hash or 'all'}:v1",
        pack_type="prompt_audit",
        policy_version=RETRIEVAL_POLICY_VERSION,
        token_budget=token_budget,
        source_refs=[str(row.get("index_id")) for row in rows if row.get("index_id")],
        summary={
            "prompt_version": prompt_version,
            "config_hash": config_hash,
            "runs": len(rows),
            "action_distribution": dict(Counter(row.get("final_action") or "UNKNOWN" for row in rows)),
            "quality_distribution": dict(Counter(row.get("quality_status") or "unknown" for row in rows)),
            "resolved_rewards": len(resolved_rewards),
            "avg_reward": _avg([reward.get("reward_scalar") for reward in resolved_rewards]),
        },
        items=items,
    )


def retrieval_pack_envelope(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": utc_now_iso(),
        "summary": pack.get("summary") or {},
        "items": pack.get("items") or [],
        "artifact_refs": [
            item.get("source_ref")
            for item in pack.get("items", [])
            if item.get("source_ref")
        ],
        "recommended_debug_queries": _pack_debug_queries(pack),
    }


def _load_episode_audit(episode: dict[str, Any]) -> dict[str, Any] | None:
    audit_path = episode.get("audit_path")
    if not audit_path:
        return None
    path = Path(str(audit_path)).expanduser()
    if not path.exists():
        return None
    try:
        return load_audit_payload(path)
    except Exception:
        return None


def _final_decision(episode: dict[str, Any]) -> dict[str, Any]:
    decisions = episode.get("decisions") or []
    for decision in decisions:
        if decision.get("stage") == "final":
            return decision
    return decisions[-1] if decisions else {}


def _worst_status(statuses: list[Any]) -> str:
    if not statuses:
        return "unknown"
    return max(
        (str(status or "unknown") for status in statuses),
        key=lambda status: QUALITY_STATUS_RANK.get(status, 1),
    )


def _pack_item(
    *,
    rank: int,
    item_type: str,
    reason: str,
    source_ref: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "item_id": f"pack_item:{rank:04d}",
        "item_type": item_type,
        "rank": rank,
        "reason": reason,
        "source_ref": source_ref,
        "token_estimate": _token_estimate(payload),
        "payload": payload,
    }


def _token_estimate(payload: Any) -> int:
    return max(1, len(str(payload or "")) // 4)


def _latest_reward(ledger: EpisodeLedger, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    episode = ledger.load_episode(str(run_id))
    rewards = (episode or {}).get("rewards") or []
    return rewards[-1] if rewards else None


def _avg(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _pack_debug_queries(pack: dict[str, Any]) -> list[str]:
    queries = []
    run_id = pack.get("run_id")
    if run_id:
        queries.append(f"python -m cli.main quality-index --run-id {run_id} --format json")
    for item in pack.get("items", [])[:3]:
        source_ref = str(item.get("source_ref") or "")
        if source_ref.startswith("tool_call:") and run_id:
            queries.append(
                f"python -m cli.main quality-open --run-id {run_id} --artifact-ref {source_ref} --no-include-output"
            )
    return queries

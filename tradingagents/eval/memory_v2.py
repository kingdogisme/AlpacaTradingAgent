from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from typing import Any

from .critic import critic_memory_candidate
from .ledger import EpisodeLedger
from .models import MemoryItemRecordV1, MemoryPromotionRecordV1


MEMORY_POLICIES = {
    "none",
    "ticker_horizon_promoted_v1",
    "ticker_horizon_candidates_v1",
    "data_quality_lessons_v1",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_memory_candidates_from_critic(
    ledger: EpisodeLedger,
    *,
    run_id: str | None = None,
    since: str | None = None,
    due_only: bool = False,
) -> list[dict[str, Any]]:
    episodes = []
    if run_id:
        episode = ledger.load_episode(run_id)
        if episode:
            episodes.append(episode)
    elif due_only:
        critic_versions = {row.get("critic_version") for row in ledger.list_critic_records()}
        for version in critic_versions or {"v1_diagnostic_tags"}:
            episodes.extend(ledger.resolved_reward_episodes_without_critic(str(version)))
    else:
        filters = {"status": "completed"}
        if since:
            filters["since"] = since
        for episode_row in ledger.list_episodes(filters):
            episode = ledger.load_episode(episode_row.run_id)
            if episode:
                episodes.append(episode)

    created: list[dict[str, Any]] = []
    for episode in episodes:
        for critic in episode.get("critic_records") or []:
            record = _memory_from_critic(episode, critic)
            ledger.add_memory_item(record)
            created.append(_candidate_payload(record))
    return created


def create_data_quality_memory_candidates(
    ledger: EpisodeLedger,
    run_id: str,
) -> list[dict[str, Any]]:
    episode = ledger.load_episode(run_id)
    if not episode:
        return []
    symbol, horizon = _episode_symbol_horizon(episode)
    quality_rows = ledger.list_quality_index(run_id)
    recon_rows = ledger.list_quality_reconciliation(run_id)
    candidates: list[MemoryItemRecordV1] = []

    risky_quality = [
        row
        for row in quality_rows
        if row.get("status") == "fail"
        or "stale_source" in (row.get("flags") or [])
        or row.get("criticality") == "critical"
    ]
    if risky_quality:
        claim = "Data quality failures or stale critical evidence should cap confidence and be disclosed in final synthesis."
        candidates.append(
            _memory_record(
                claim=claim,
                memory_type="data_quality_candidate",
                symbol=symbol,
                horizon=horizon,
                created_by="data_quality_v2",
                source_run_id=run_id,
                supporting_refs=[row.get("artifact_ref") for row in risky_quality if row.get("artifact_ref")],
                metadata={"quality_flags": sorted({flag for row in risky_quality for flag in (row.get("flags") or [])})},
            )
        )
    mismatch_rows = [
        row
        for row in recon_rows
        if "cross_source_price_mismatch" in (row.get("flags") or [])
    ]
    if mismatch_rows:
        candidates.append(
            _memory_record(
                claim="Cross-source price mismatches should be treated as degraded evidence until the primary source is verified.",
                memory_type="data_quality_candidate",
                symbol=symbol,
                horizon=horizon,
                created_by="data_quality_v2",
                source_run_id=run_id,
                supporting_refs=[row.get("reconciliation_id") for row in mismatch_rows],
                metadata={"reconciliation_flags": ["cross_source_price_mismatch"]},
            )
        )

    created = []
    for record in candidates:
        ledger.add_memory_item(record)
        created.append(_candidate_payload(record))
    return created


def normalize_legacy_memory_items(ledger: EpisodeLedger) -> list[dict[str, Any]]:
    normalized = []
    for item in ledger.list_memory_items():
        evidence = item.get("evidence_json") or {}
        metadata = item.get("metadata_json") or {}
        run_id = item.get("source_run_id") or evidence.get("run_id")
        episode = ledger.load_episode(str(run_id)) if run_id else None
        symbol, horizon = _episode_symbol_horizon(episode or {})
        record = MemoryItemRecordV1(
            memory_item_id=item["memory_item_id"],
            memory_type=item["memory_type"],
            content=item["content"],
            source=item.get("source") or "legacy",
            status=item.get("state") or item.get("status") or "candidate",
            evidence_json=evidence,
            metadata_json=metadata,
            created_at=item.get("created_at"),
            symbol=item.get("symbol") or symbol,
            horizon=item.get("horizon") or horizon,
            state=item.get("state") or item.get("status") or "candidate",
            created_by=item.get("created_by") or item.get("source") or "legacy",
            promotion_score=float(item.get("promotion_score") or 0.0),
            last_evaluated_at=item.get("last_evaluated_at"),
            source_run_id=run_id,
            source_ref=item.get("source_ref") or (f"episode:{run_id}" if run_id else None),
        )
        ledger.add_memory_item(record)
        normalized.append(_candidate_payload(record))
    return normalized


def retrieve_memory(
    ledger: EpisodeLedger,
    *,
    run_id: str,
    stage: str,
    policy: str,
    limit: int = 5,
) -> dict[str, Any]:
    if policy not in MEMORY_POLICIES:
        raise ValueError(f"Unsupported memory policy: {policy}")
    episode = ledger.load_episode(run_id)
    symbol, horizon = _episode_symbol_horizon(episode or {})
    if policy == "none":
        items: list[dict[str, Any]] = []
    elif policy == "ticker_horizon_promoted_v1":
        items = ledger.list_memory_items(symbol=symbol, horizon=horizon, state="promoted")
    elif policy == "ticker_horizon_candidates_v1":
        items = ledger.list_memory_items(symbol=symbol, horizon=horizon)
    else:
        items = [
            item
            for item in ledger.list_memory_items(symbol=symbol, horizon=horizon, state="promoted")
            if item.get("memory_type") == "data_quality_candidate"
            or "data quality" in str(item.get("content") or "").lower()
            or "cross-source" in str(item.get("content") or "").lower()
        ]
    ranked = []
    for rank, item in enumerate(items[:limit], start=1):
        score = _memory_score(item)
        ledger.record_memory_retrieval(
            run_id,
            item["memory_item_id"],
            stage,
            rank,
            score,
            metadata={
                "policy_version": policy,
                "source_ref": item.get("source_ref") or f"memory:{item['memory_item_id']}",
                "state": item.get("state") or item.get("status"),
                "untrusted": (item.get("state") or item.get("status")) != "promoted",
            },
        )
        ranked.append(
            {
                "memory_id": item["memory_item_id"],
                "state": item.get("state") or item.get("status"),
                "memory_type": item.get("memory_type"),
                "claim": item.get("content"),
                "symbol": item.get("symbol"),
                "horizon": item.get("horizon"),
                "rank": rank,
                "score": score,
                "source_ref": item.get("source_ref"),
                "untrusted": (item.get("state") or item.get("status")) != "promoted",
            }
        )
    return {
        "run_id": run_id,
        "policy_version": policy,
        "summary": {"retrieved_count": len(ranked), "stage": stage, "symbol": symbol, "horizon": horizon},
        "items": ranked,
        "artifact_refs": [item.get("source_ref") for item in ranked if item.get("source_ref")],
        "recommended_debug_queries": [
            f"python -m tradingagents.eval memory-candidates --run-id {run_id} --format json",
            f"python -m tradingagents.eval memory-report --symbol {symbol or '<symbol>'} --horizon {horizon or '<horizon>'} --format json",
        ],
    }


def promote_memory(
    ledger: EpisodeLedger,
    *,
    memory_id: str,
    reason: str,
    promoted_by: str,
    allow_manual: bool = False,
) -> dict[str, Any]:
    item = ledger.load_memory_item(memory_id)
    if not item:
        raise ValueError(f"Memory item not found: {memory_id}")
    refs = _supporting_refs(item)
    if not refs:
        raise ValueError("Memory promotion requires supporting refs.")
    source_run_id = item.get("source_run_id") or (item.get("evidence_json") or {}).get("run_id")
    has_resolved_reward = _has_resolved_reward(ledger, source_run_id)
    if not has_resolved_reward and not allow_manual:
        raise ValueError("Memory promotion requires resolved reward or --allow-manual.")
    ledger.add_memory_promotion(
        MemoryPromotionRecordV1(
            memory_item_id=memory_id,
            from_status=item.get("state") or item.get("status") or "candidate",
            to_status="promoted",
            reason=reason,
            promoted_by=promoted_by,
            evidence_json={"supporting_refs": refs, "source_run_id": source_run_id},
        )
    )
    return ledger.load_memory_item(memory_id) or {}


def demote_memory(
    ledger: EpisodeLedger,
    *,
    memory_id: str,
    reason: str,
    demoted_by: str = "user",
) -> dict[str, Any]:
    item = ledger.load_memory_item(memory_id)
    if not item:
        raise ValueError(f"Memory item not found: {memory_id}")
    ledger.add_memory_promotion(
        MemoryPromotionRecordV1(
            memory_item_id=memory_id,
            from_status=item.get("state") or item.get("status") or "candidate",
            to_status="demoted",
            reason=reason,
            promoted_by=demoted_by,
            evidence_json={"supporting_refs": _supporting_refs(item), "source_run_id": item.get("source_run_id")},
        )
    )
    return ledger.load_memory_item(memory_id) or {}


def memory_report(
    ledger: EpisodeLedger,
    *,
    symbol: str | None = None,
    horizon: str | None = None,
) -> dict[str, Any]:
    items = ledger.list_memory_items(symbol=symbol, horizon=horizon)
    retrievals = _memory_retrieval_rows(ledger)
    demotion_candidates = _demotion_candidates(ledger, items, retrievals)
    return {
        "generated_at": utc_now_iso(),
        "summary": {
            "total": len(items),
            "by_state": dict(Counter(item.get("state") or item.get("status") for item in items)),
            "by_type": dict(Counter(item.get("memory_type") for item in items)),
            "retrievals": len(retrievals),
            "demotion_candidates": len(demotion_candidates),
        },
        "items": [_memory_json(item) for item in items],
        "demotion_candidates": demotion_candidates,
        "artifact_refs": [item.get("source_ref") for item in items if item.get("source_ref")],
        "recommended_debug_queries": ["python -m tradingagents.eval memory-retrieve --run-id <run_id> --stage risk_manager --policy ticker_horizon_promoted_v1 --format json"],
    }


def memory_ablation(
    ledger: EpisodeLedger,
    *,
    since: str | None,
    policies: list[str],
) -> dict[str, Any]:
    rows = ledger.report_rows(since=since)
    retrievals = _memory_retrieval_rows(ledger)
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for retrieval in retrievals:
        policy = (retrieval.get("metadata_json") or {}).get("policy_version") or "unknown"
        by_policy[policy].append(retrieval)
    results = []
    for policy in policies:
        policy_retrievals = by_policy.get(policy, []) if policy != "none" else []
        run_ids = {row.get("run_id") for row in policy_retrievals}
        relevant = [row for row in rows if policy == "none" or row.get("run_id") in run_ids]
        resolved = [row for row in relevant if row.get("reward_scalar") is not None]
        results.append(
            {
                "policy": policy,
                "retrieved_count": len(policy_retrievals),
                "resolved_runs": len(resolved),
                "avg_reward": _avg([row.get("reward_scalar") for row in resolved]),
                "avg_alpha": _avg([row.get("alpha_return") for row in resolved]),
                "action_distribution": dict(Counter(row.get("action") or "UNKNOWN" for row in relevant)),
                "failure_tags": dict(Counter(tag for row in relevant for tag in (row.get("critic_failure_tags") or []))),
                "promoted_memory_hit_rate": _promoted_hit_rate(policy_retrievals),
            }
        )
    return {"generated_at": utc_now_iso(), "summary": {"policies": len(results)}, "policies": results}


def _memory_from_critic(episode: dict[str, Any], critic: dict[str, Any]) -> MemoryItemRecordV1:
    base = critic_memory_candidate(
        type("CriticLike", (), {
            "run_id": critic["run_id"],
            "critic_version": critic["critic_version"],
            "failure_tags": critic.get("failure_tags") or [],
            "reflection_text": critic.get("reflection_text") or "",
            "improvement_candidates": critic.get("improvement_candidates") or [],
            "created_at": critic.get("created_at"),
        })()
    )
    symbol, horizon = _episode_symbol_horizon(episode)
    evidence = {
        **(base.evidence_json or {}),
        "symbol": symbol,
        "horizon": horizon,
        "source_ref": f"critic_record:{critic['run_id']}:{critic['critic_version']}",
        "supporting_refs": [f"critic_record:{critic['run_id']}:{critic['critic_version']}"],
    }
    return MemoryItemRecordV1(
        memory_item_id=base.memory_item_id,
        memory_type=base.memory_type,
        content=base.content,
        source=base.source,
        status="candidate",
        evidence_json=evidence,
        metadata_json=base.metadata_json,
        created_at=base.created_at,
        symbol=symbol,
        horizon=horizon,
        state="candidate",
        created_by=f"critic:{critic['critic_version']}",
        promotion_score=0.0,
        source_run_id=critic["run_id"],
        source_ref=evidence["source_ref"],
    )


def _memory_record(
    *,
    claim: str,
    memory_type: str,
    symbol: str | None,
    horizon: str | None,
    created_by: str,
    source_run_id: str,
    supporting_refs: list[Any],
    metadata: dict[str, Any],
) -> MemoryItemRecordV1:
    refs = [str(ref) for ref in supporting_refs if ref]
    memory_id = _stable_memory_id(symbol, horizon, memory_type, claim, refs)
    return MemoryItemRecordV1(
        memory_item_id=memory_id,
        memory_type=memory_type,
        content=claim,
        source=created_by,
        status="candidate",
        evidence_json={
            "run_id": source_run_id,
            "symbol": symbol,
            "horizon": horizon,
            "supporting_refs": refs,
            "source_ref": refs[0] if refs else f"episode:{source_run_id}",
        },
        metadata_json=metadata,
        symbol=symbol,
        horizon=horizon,
        state="candidate",
        created_by=created_by,
        promotion_score=0.0,
        source_run_id=source_run_id,
        source_ref=refs[0] if refs else f"episode:{source_run_id}",
    )


def _stable_memory_id(symbol: str | None, horizon: str | None, memory_type: str, claim: str, refs: list[str]) -> str:
    digest = hashlib.sha1("|".join([claim, *refs]).encode("utf-8")).hexdigest()[:12]
    return f"memory:{symbol or 'unknown'}:{horizon or 'unknown'}:{memory_type}:{digest}"


def _candidate_payload(record: MemoryItemRecordV1) -> dict[str, Any]:
    return {
        "memory_id": record.memory_item_id,
        "state": record.state or record.status,
        "memory_type": record.memory_type,
        "claim": record.content,
        "symbol": record.symbol,
        "horizon": record.horizon,
        "supporting_refs": (record.evidence_json or {}).get("supporting_refs")
        or [(record.evidence_json or {}).get("source_ref")]
        or [],
        "created_by": record.created_by or record.source,
        "promotion_score": record.promotion_score,
        "source_run_id": record.source_run_id,
    }


def _memory_json(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence_json") or {}
    return {
        "memory_id": item.get("memory_item_id"),
        "state": item.get("state") or item.get("status"),
        "memory_type": item.get("memory_type"),
        "claim": item.get("content"),
        "symbol": item.get("symbol"),
        "horizon": item.get("horizon"),
        "supporting_refs": evidence.get("supporting_refs") or [item.get("source_ref")],
        "created_by": item.get("created_by") or item.get("source"),
        "promotion_score": item.get("promotion_score") or 0.0,
        "source_run_id": item.get("source_run_id") or evidence.get("run_id"),
        "source_ref": item.get("source_ref"),
    }


def _episode_symbol_horizon(episode: dict[str, Any]) -> tuple[str | None, str | None]:
    if not episode:
        return None, None
    final = next((decision for decision in episode.get("decisions", []) if decision.get("stage") == "final"), {})
    return (
        episode.get("symbol"),
        final.get("horizon")
        or (episode.get("config") or {}).get("trading_horizon")
        or (episode.get("metadata") or {}).get("trading_horizon"),
    )


def _supporting_refs(item: dict[str, Any]) -> list[str]:
    evidence = item.get("evidence_json") or {}
    refs = evidence.get("supporting_refs") or []
    if item.get("source_ref"):
        refs.append(item["source_ref"])
    return sorted({str(ref) for ref in refs if ref})


def _has_resolved_reward(ledger: EpisodeLedger, run_id: str | None) -> bool:
    if not run_id:
        return False
    episode = ledger.load_episode(str(run_id))
    return any(reward.get("reward_status", "resolved") == "resolved" for reward in (episode or {}).get("rewards", []))


def _memory_score(item: dict[str, Any]) -> float:
    base = float(item.get("promotion_score") or 0.0)
    return base + (1.0 if (item.get("state") or item.get("status")) == "promoted" else 0.0)


def _memory_retrieval_rows(ledger: EpisodeLedger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:  # noqa: SLF001 - internal eval helper keeps this query local.
        rows = conn.execute("SELECT * FROM memory_retrievals ORDER BY created_at").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata_json"] = _json_load(item.get("metadata_json"))
        result.append(item)
    return result


def _json_load(value: Any) -> Any:
    import json

    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _demotion_candidates(
    ledger: EpisodeLedger,
    items: list[dict[str, Any]],
    retrievals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_memory = defaultdict(list)
    for retrieval in retrievals:
        by_memory[retrieval.get("memory_item_id")].append(retrieval)
    candidates = []
    for item in items:
        bad_runs = []
        for retrieval in by_memory.get(item.get("memory_item_id"), []):
            episode = ledger.load_episode(str(retrieval.get("run_id")))
            rewards = (episode or {}).get("rewards") or []
            critics = (episode or {}).get("critic_records") or []
            if any((reward.get("reward_scalar") is not None and float(reward["reward_scalar"]) < 0) for reward in rewards):
                bad_runs.append(retrieval.get("run_id"))
            elif any(
                tag in {"wrong_direction", "underperformed_benchmark"}
                for critic in critics
                for tag in (critic.get("failure_tags") or [])
            ):
                bad_runs.append(retrieval.get("run_id"))
        if bad_runs:
            candidates.append(
                {
                    "memory_id": item.get("memory_item_id"),
                    "reason": "retrieval correlated with negative reward or failure tags",
                    "supporting_refs": [f"episode:{run_id}" for run_id in sorted(set(bad_runs))],
                }
            )
    return candidates


def _promoted_hit_rate(retrievals: list[dict[str, Any]]) -> float | None:
    if not retrievals:
        return None
    hits = [
        1
        for retrieval in retrievals
        if not (retrieval.get("metadata_json") or {}).get("untrusted")
    ]
    return sum(hits) / len(retrievals)


def _avg(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)

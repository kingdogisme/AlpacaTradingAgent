from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .benchmarking import compare_existing_runs, load_benchmark_suite
from .ledger import EpisodeLedger
from .reporting import soft_gate_audit


DEFAULT_MIN_RESOLVED = 5


@dataclass(frozen=True)
class EvalRunVariant:
    prompt_version: str | None = None
    config_hash: str | None = None
    experiment_id: str | None = None
    model_provider: str | None = None
    memory_policy: str | None = None
    policy_version: str | None = None

    @classmethod
    def from_filter(cls, values: dict[str, Any] | None = None) -> "EvalRunVariant":
        values = values or {}
        return cls(
            prompt_version=values.get("prompt_version"),
            config_hash=values.get("config_hash"),
            experiment_id=values.get("experiment_id"),
            model_provider=values.get("model_provider"),
            memory_policy=values.get("memory_policy"),
            policy_version=values.get("policy_version"),
        )

    def as_filter(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value}


@dataclass(frozen=True)
class EvalMetricSet:
    sample_count: int
    resolved_count: int
    pending_count: int
    action_distribution: dict[str, int]
    trader_action_distribution: dict[str, int]
    analyst_to_final_downgrade_rate: float | None
    risk_veto_rate: float | None
    soft_gate_over_veto_rate: float | None
    trigger_met_but_no_action_rate: float | None
    trigger_drift_rate: float | None
    avg_counterfactual_advantage: float | None
    avg_reward: float | None
    avg_alpha: float | None
    quality_flags: dict[str, int] = field(default_factory=dict)


def build_harness_report(
    ledger: EpisodeLedger,
    *,
    suite_path: str | Path | None = None,
    since: str | None = None,
    include_high_leakage: bool = False,
    variant_filter: dict[str, Any] | None = None,
    baseline_filter: dict[str, Any] | None = None,
    candidate_filter: dict[str, Any] | None = None,
    min_resolved: int = DEFAULT_MIN_RESOLVED,
) -> dict[str, Any]:
    selected_filter = variant_filter or candidate_filter or {}
    rows = _select_rows(
        ledger,
        suite_path=suite_path,
        since=since,
        include_high_leakage=include_high_leakage,
        variant_filter=selected_filter,
    )
    rows = [_enrich_row_with_episode(ledger, row) for row in rows]
    metrics = compute_metric_set(rows)
    hypotheses = evaluate_hypotheses(rows, metrics=metrics, min_resolved=min_resolved)
    suite = load_benchmark_suite(suite_path) if suite_path else None
    comparison = (
        compare_existing_runs(
            ledger,
            suite,
            baseline_filter=baseline_filter or {},
            candidate_filter=candidate_filter or {},
            include_high_leakage=include_high_leakage,
        )
        if suite and baseline_filter and candidate_filter
        else None
    )
    return {
        "report_type": "eval_harness_report",
        "suite": _suite_summary(suite),
        "variant": EvalRunVariant.from_filter(selected_filter).as_filter(),
        "baseline_variant": EvalRunVariant.from_filter(baseline_filter).as_filter(),
        "candidate_variant": EvalRunVariant.from_filter(candidate_filter).as_filter(),
        "filters": {
            "since": since,
            "include_high_leakage": include_high_leakage,
            "min_resolved": min_resolved,
        },
        "metrics": metrics.__dict__,
        "hypotheses": hypotheses,
        "comparison": comparison,
        "sample": {
            "run_ids": [row.get("run_id") for row in rows if row.get("run_id")][:25],
            "representative_runs": _representative_runs(rows),
        },
        "quality": {
            "insufficient_sample": metrics.resolved_count < min_resolved,
            "confidence_risk": _confidence_risk(metrics, min_resolved),
        },
        "recommended_debug_queries": _debug_queries(rows),
    }


def build_hypothesis_report(
    ledger: EpisodeLedger,
    *,
    since: str | None = None,
    include_high_leakage: bool = False,
    min_resolved: int = DEFAULT_MIN_RESOLVED,
) -> dict[str, Any]:
    rows = [_enrich_row_with_episode(ledger, row) for row in ledger.report_rows(since=since, include_high_leakage=include_high_leakage)]
    metrics = compute_metric_set(rows)
    return {
        "report_type": "hypothesis_report",
        "filters": {
            "since": since,
            "include_high_leakage": include_high_leakage,
            "min_resolved": min_resolved,
        },
        "metrics": metrics.__dict__,
        "hypotheses": evaluate_hypotheses(rows, metrics=metrics, min_resolved=min_resolved),
        "quality": {
            "insufficient_sample": metrics.resolved_count < min_resolved,
            "confidence_risk": _confidence_risk(metrics, min_resolved),
        },
        "recommended_debug_queries": _debug_queries(rows),
    }


def compute_metric_set(rows: list[dict[str, Any]]) -> EvalMetricSet:
    resolved = [row for row in rows if row.get("reward_scalar") is not None]
    final_actions = Counter(row.get("action") or "UNKNOWN" for row in rows)
    trader_actions = Counter(row.get("trader_action") or "UNKNOWN" for row in rows)
    soft_audit = soft_gate_audit(rows)
    return EvalMetricSet(
        sample_count=len(rows),
        resolved_count=len(resolved),
        pending_count=len(rows) - len(resolved),
        action_distribution=dict(final_actions),
        trader_action_distribution=dict(trader_actions),
        analyst_to_final_downgrade_rate=_rate(rows, _is_analyst_to_final_downgrade),
        risk_veto_rate=_rate(rows, _is_risk_veto),
        soft_gate_over_veto_rate=_tag_rate(rows, "soft_gate_over_veto"),
        trigger_met_but_no_action_rate=_tag_rate(rows, "trigger_met_but_no_action"),
        trigger_drift_rate=_tag_rate(rows, "moving_trigger"),
        avg_counterfactual_advantage=soft_audit.get("avg_risk_veto_counterfactual_advantage"),
        avg_reward=_avg([row.get("reward_scalar") for row in resolved]),
        avg_alpha=_avg([row.get("alpha_return") for row in resolved if row.get("alpha_return") is not None]),
        quality_flags=_quality_flags(rows),
    )


def evaluate_hypotheses(
    rows: list[dict[str, Any]],
    *,
    metrics: EvalMetricSet | None = None,
    min_resolved: int = DEFAULT_MIN_RESOLVED,
) -> dict[str, Any]:
    metrics = metrics or compute_metric_set(rows)
    return {
        "H1_hold_bias": _evaluate_h1(rows, metrics, min_resolved),
        "H2_soft_gate_over_veto": _evaluate_h2(rows, metrics, min_resolved),
        "H3_trigger_drift": _evaluate_h3(rows, metrics, min_resolved),
    }


def _select_rows(
    ledger: EpisodeLedger,
    *,
    suite_path: str | Path | None,
    since: str | None,
    include_high_leakage: bool,
    variant_filter: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    rows = ledger.report_rows(since=since, include_high_leakage=include_high_leakage)
    rows = _filter_variant(rows, variant_filter or {})
    if not suite_path:
        return rows
    suite = load_benchmark_suite(suite_path)
    wanted = {(case["symbol"], case["trade_date"], case["horizon"]) for case in suite.get("cases") or []}
    case_by_key = {
        (case["symbol"], case["trade_date"], case["horizon"]): case["case_id"]
        for case in suite.get("cases") or []
    }
    selected = [
        {**row, "case_id": case_by_key.get((row.get("symbol"), row.get("trade_date"), row.get("horizon")))}
        for row in rows
        if (row.get("symbol"), row.get("trade_date"), row.get("horizon")) in wanted
    ]
    return selected


def _filter_variant(rows: list[dict[str, Any]], variant_filter: dict[str, Any]) -> list[dict[str, Any]]:
    if not variant_filter:
        return rows
    result = []
    for row in rows:
        if all(str(row.get(key) or "") == str(value) for key, value in variant_filter.items() if value):
            result.append(row)
    return result


def _enrich_row_with_episode(ledger: EpisodeLedger, row: dict[str, Any]) -> dict[str, Any]:
    episode = ledger.load_episode(str(row.get("run_id"))) if row.get("run_id") else None
    if not episode:
        return row
    decisions = {decision.get("stage"): decision for decision in episode.get("decisions") or []}
    metadata = episode.get("metadata") or {}
    return {
        **row,
        "research_manager_action": (decisions.get("research_manager") or {}).get("action"),
        "trader_action": (decisions.get("trader") or {}).get("action"),
        "active_plan_review": metadata.get("active_plan_review") or {},
        "case_id": row.get("case_id") or metadata.get("case_id"),
    }


def _evaluate_h1(rows: list[dict[str, Any]], metrics: EvalMetricSet, min_resolved: int) -> dict[str, Any]:
    if metrics.resolved_count < min_resolved:
        return _hypothesis("insufficient_sample", "resolved sample below threshold", metrics)
    final_hold = _action_rate(rows, "action", {"HOLD", "NEUTRAL"})
    trader_hold = _action_rate(rows, "trader_action", {"HOLD", "NEUTRAL"})
    tags = Counter(tag for row in rows for tag in row.get("critic_failure_tags", []))
    supported = (
        final_hold is not None
        and trader_hold is not None
        and final_hold - trader_hold >= 0.20
        and (tags.get("missed_directional_move", 0) + tags.get("over_conservative_hold", 0)) / max(len(rows), 1) >= 0.20
    )
    contradicted = final_hold is not None and trader_hold is not None and final_hold <= trader_hold + 0.05
    return {
        "status": "supported" if supported else ("contradicted" if contradicted else "inconclusive"),
        "reason": "final HOLD materially exceeds trader HOLD with recurring missed/over-conservative tags",
        "metrics": {
            "final_hold_rate": final_hold,
            "trader_hold_rate": trader_hold,
            "missed_directional_move_count": tags.get("missed_directional_move", 0),
            "over_conservative_hold_count": tags.get("over_conservative_hold", 0),
        },
        "evidence_run_ids": _runs_with_tags(rows, {"missed_directional_move", "over_conservative_hold"}),
    }


def _evaluate_h2(rows: list[dict[str, Any]], metrics: EvalMetricSet, min_resolved: int) -> dict[str, Any]:
    if metrics.resolved_count < min_resolved:
        return _hypothesis("insufficient_sample", "resolved sample below threshold", metrics)
    tagged = [
        row for row in rows
        if "soft_gate_over_veto" in row.get("critic_failure_tags", []) or _is_risk_veto(row)
    ]
    advantage = metrics.avg_counterfactual_advantage
    supported = len(tagged) >= max(2, min_resolved // 3) and advantage is not None and advantage > 0
    contradicted = len(tagged) > 0 and advantage is not None and advantage <= 0
    return {
        "status": "supported" if supported else ("contradicted" if contradicted else "inconclusive"),
        "reason": "risk-veto/soft-gate cases have better risk-veto counterfactual reward than final action",
        "metrics": {
            "tagged_count": len(tagged),
            "soft_gate_over_veto_rate": metrics.soft_gate_over_veto_rate,
            "risk_veto_rate": metrics.risk_veto_rate,
            "avg_counterfactual_advantage": advantage,
        },
        "evidence_run_ids": [row.get("run_id") for row in tagged if row.get("run_id")][:10],
    }


def _evaluate_h3(rows: list[dict[str, Any]], metrics: EvalMetricSet, min_resolved: int) -> dict[str, Any]:
    if metrics.sample_count < min_resolved:
        return _hypothesis("insufficient_sample", "sample below threshold", metrics)
    tagged = [
        row for row in rows
        if any(tag in row.get("critic_failure_tags", []) for tag in ("moving_trigger", "trigger_met_but_no_action"))
    ]
    supported = len(tagged) >= max(1, min_resolved // 4)
    return {
        "status": "supported" if supported else "inconclusive",
        "reason": "trigger-met lifecycle rows show moving-trigger or no-action tags",
        "metrics": {
            "trigger_drift_rate": metrics.trigger_drift_rate,
            "trigger_met_but_no_action_rate": metrics.trigger_met_but_no_action_rate,
            "tagged_count": len(tagged),
        },
        "evidence_run_ids": [row.get("run_id") for row in tagged if row.get("run_id")][:10],
    }


def _hypothesis(status: str, reason: str, metrics: EvalMetricSet) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "metrics": {
            "sample_count": metrics.sample_count,
            "resolved_count": metrics.resolved_count,
        },
        "evidence_run_ids": [],
    }


def _rate(rows: list[dict[str, Any]], predicate) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if predicate(row)) / len(rows)


def _tag_rate(rows: list[dict[str, Any]], tag: str) -> float | None:
    return _rate(rows, lambda row: tag in (row.get("critic_failure_tags") or []))


def _action_rate(rows: list[dict[str, Any]], field: str, actions: set[str]) -> float | None:
    known = [row for row in rows if row.get(field)]
    if not known:
        return None
    return sum(1 for row in known if row.get(field) in actions) / len(known)


def _is_analyst_to_final_downgrade(row: dict[str, Any]) -> bool:
    final = row.get("action")
    trader = row.get("trader_action") or row.get("research_manager_action")
    return final in {"HOLD", "NEUTRAL"} and trader in {"BUY", "LONG", "SELL", "SHORT"}


def _is_risk_veto(row: dict[str, Any]) -> bool:
    final = row.get("action")
    trader = row.get("trader_action")
    return final in {"HOLD", "NEUTRAL"} and trader in {"BUY", "LONG", "SELL", "SHORT"}


def _quality_flags(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for row in rows:
        for flag in row.get("critic_failure_tags") or []:
            counter[flag] += 1
        for flag in (row.get("metadata") or {}).get("quality_flags", []) or []:
            counter[flag] += 1
    return dict(counter)


def _avg(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _runs_with_tags(rows: list[dict[str, Any]], tags: set[str]) -> list[str]:
    return [
        row.get("run_id")
        for row in rows
        if row.get("run_id") and any(tag in (row.get("critic_failure_tags") or []) for tag in tags)
    ][:10]


def _representative_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reps = []
    for row in rows:
        tags = row.get("critic_failure_tags") or []
        if tags or row.get("reward_scalar") is not None:
            reps.append(
                {
                    "run_id": row.get("run_id"),
                    "case_id": row.get("case_id"),
                    "symbol": row.get("symbol"),
                    "trade_date": row.get("trade_date"),
                    "horizon": row.get("horizon"),
                    "action": row.get("action"),
                    "trader_action": row.get("trader_action"),
                    "reward_scalar": row.get("reward_scalar"),
                    "critic_failure_tags": tags,
                }
            )
    return reps[:10]


def _debug_queries(rows: list[dict[str, Any]]) -> list[str]:
    run_id = next((row.get("run_id") for row in rows if row.get("run_id")), "<run_id>")
    return [
        f"python -m tradingagents.eval hypothesis-report --since <date> --format json",
        f"python -m tradingagents.eval soft-gate-audit --since <date> --format json",
        f"python -m tradingagents.eval memory-candidates --run-id {run_id} --format json",
        f"python -m cli.main retrieval-pack --type risk_review --run-id {run_id} --format json",
    ]


def _confidence_risk(metrics: EvalMetricSet, min_resolved: int) -> str:
    if metrics.resolved_count < min_resolved:
        return "high_insufficient_resolved_sample"
    if metrics.sample_count < min_resolved * 2:
        return "medium_small_sample"
    return "low_enough_for_directional_audit"


def _suite_summary(suite: dict[str, Any] | None) -> dict[str, Any] | None:
    if not suite:
        return None
    return {
        "suite_id": suite.get("suite_id"),
        "case_count": len(suite.get("cases") or []),
        "suite_path": suite.get("suite_path"),
    }

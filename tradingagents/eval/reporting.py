from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def summarize_rows(rows: list[dict[str, Any]], group_by: list[str] | None = None) -> list[dict[str, Any]]:
    group_by = group_by or []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(_group_value(row, field) for field in group_by) if group_by else ("all",)
        groups[key].append(row)

    summaries = []
    for key, items in groups.items():
        resolved = [item for item in items if item.get("reward_scalar") is not None]
        actions = Counter(item.get("action") or "UNKNOWN" for item in items)
        confusion = Counter(
            f"{item.get('action') or 'UNKNOWN'}->{item.get('oracle_label') or 'PENDING'}"
            for item in items
        )
        reward_statuses = Counter(item.get("reward_status") or "pending" for item in items)
        leakage = Counter(
            item.get("leakage_risk")
            or (item.get("metadata") or {}).get("data_leakage_risk", "unknown")
            for item in items
        )
        critic_tags = Counter(
            tag
            for item in items
            for tag in (item.get("critic_failure_tags") or [])
        )
        hits = [
            1
            for item in resolved
            if item.get("action") is not None and item.get("action") == item.get("oracle_label")
        ]
        summary = {
            "group": dict(zip(group_by, key)) if group_by else {"all": "all"},
            "episodes": len(items),
            "resolved": len(resolved),
            "pending": len(items) - len(resolved),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "reward_status_distribution": dict(reward_statuses),
            "data_leakage_distribution": dict(leakage),
            "action_distribution": dict(actions),
            "oracle_confusion": dict(confusion),
            "critic_failure_tags": dict(critic_tags),
            "memory_candidate_count": sum(int(item.get("memory_candidate_count") or 0) for item in items),
            "trace_coverage_rate": (
                sum(1 for item in items if int(item.get("trace_span_count") or 0) > 0) / len(items)
            )
            if items
            else None,
            "hit_rate": (sum(hits) / len(resolved)) if resolved else None,
            "avg_raw_return": _avg([item.get("raw_return") for item in resolved]),
            "avg_alpha": _avg([item.get("alpha_return") for item in resolved if item.get("alpha_return") is not None]),
            "avg_reward": _avg([item.get("reward_scalar") for item in resolved]),
            "soft_gate_audit": soft_gate_audit(items),
        }
        summaries.append(summary)
    return summaries


def soft_gate_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    relevant = [
        row for row in rows
        if any(
            tag in (row.get("critic_failure_tags") or [])
            for tag in ("soft_gate_over_veto", "over_conservative_hold", "trigger_met_but_no_action")
        )
    ]
    counterfactual_advantages = []
    for row in rows:
        counterfactuals = (row.get("reward_components") or {}).get("counterfactual_rewards") or {}
        final_reward = _scenario_reward(counterfactuals, "final_action")
        veto_reward = _scenario_reward(counterfactuals, "risk_manager_veto")
        if final_reward is not None and veto_reward is not None:
            counterfactual_advantages.append(veto_reward - final_reward)
    return {
        "episodes": len(rows),
        "flagged_soft_gate_over_veto": sum("soft_gate_over_veto" in (row.get("critic_failure_tags") or []) for row in rows),
        "flagged_over_conservative_hold": sum("over_conservative_hold" in (row.get("critic_failure_tags") or []) for row in rows),
        "flagged_trigger_met_but_no_action": sum("trigger_met_but_no_action" in (row.get("critic_failure_tags") or []) for row in rows),
        "flag_rate": (len(relevant) / len(rows)) if rows else None,
        "avg_risk_veto_counterfactual_advantage": _avg(counterfactual_advantages),
        "recommendation": _soft_gate_recommendation(relevant, counterfactual_advantages, rows),
    }


def _avg(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _scenario_reward(counterfactuals: dict[str, Any], key: str) -> float | None:
    scenario = counterfactuals.get(key)
    if not isinstance(scenario, dict) or scenario.get("pnl_reward") is None:
        return None
    return float(scenario["pnl_reward"])


def _soft_gate_recommendation(
    relevant: list[dict[str, Any]],
    counterfactual_advantages: list[float],
    rows: list[dict[str, Any]],
) -> str:
    if not rows:
        return "no_data"
    flag_rate = len(relevant) / len(rows)
    avg_advantage = _avg(counterfactual_advantages) or 0.0
    if flag_rate >= 0.20 and avg_advantage > 0:
        return "soft_gates_likely_over_vetoing; review multipliers and hard-block settings"
    if flag_rate == 0:
        return "no_soft_gate_over_veto_detected"
    return "mixed; keep audit-first and compare avoided losses versus missed entries"


def _group_value(row: dict[str, Any], field: str) -> Any:
    if field == "model":
        config = row.get("config") or {}
        return f"{config.get('quick_think_llm', 'unknown')}/{config.get('deep_think_llm', 'unknown')}"
    if field == "horizon":
        return row.get("horizon") or (row.get("config") or {}).get("trading_horizon") or "unknown"
    if field == "symbol":
        return row.get("symbol") or "unknown"
    if field == "data_leakage_risk":
        return (row.get("metadata") or {}).get("data_leakage_risk", "unknown")
    if field == "leakage_risk":
        return row.get("leakage_risk") or (row.get("metadata") or {}).get("data_leakage_risk", "unknown")
    if field == "experiment":
        return row.get("experiment_id") or row.get("config_hash") or "unknown"
    if field == "config_hash":
        return row.get("config_hash") or "unknown"
    return row.get(field) or "unknown"

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .indexing import rebuild_run_indexes, utc_now_iso
from .ledger import EpisodeLedger


def load_benchmark_suite(path: str | Path) -> dict[str, Any]:
    suite_path = Path(path).expanduser()
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    suite_id = payload.get("suite_id")
    cases = payload.get("cases")
    if not suite_id or not isinstance(cases, list):
        raise ValueError("Benchmark suite must include suite_id and cases list.")
    normalized_cases = []
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Benchmark case at index {idx} must be an object.")
        missing = [
            key
            for key in ("case_id", "symbol", "trade_date", "horizon")
            if not case.get(key)
        ]
        if missing:
            raise ValueError(f"Benchmark case at index {idx} missing: {', '.join(missing)}")
        normalized_cases.append(
            {
                "case_id": str(case["case_id"]),
                "symbol": str(case["symbol"]),
                "trade_date": str(case["trade_date"]),
                "horizon": str(case["horizon"]),
                "leakage_policy": str(case.get("leakage_policy") or "point_in_time"),
            }
        )
    payload["cases"] = sorted(
        normalized_cases,
        key=lambda item: (item["symbol"], item["trade_date"], item["horizon"], item["case_id"]),
    )
    payload["suite_path"] = str(suite_path)
    return payload


def compare_existing_runs(
    ledger: EpisodeLedger,
    suite: dict[str, Any],
    *,
    baseline_filter: dict[str, Any],
    candidate_filter: dict[str, Any],
    include_high_leakage: bool = False,
) -> dict[str, Any]:
    case_diffs: list[dict[str, Any]] = []
    missing_cases: list[dict[str, Any]] = []

    for case in suite.get("cases") or []:
        rebuild_run_indexes(
            ledger,
            symbol=case["symbol"],
            since=case["trade_date"],
            until=case["trade_date"],
        )
        baseline = _select_run_for_case(
            ledger,
            case,
            baseline_filter,
            include_high_leakage=include_high_leakage,
        )
        candidate = _select_run_for_case(
            ledger,
            case,
            candidate_filter,
            include_high_leakage=include_high_leakage,
        )
        if not baseline or not candidate:
            missing = {
                "case_id": case["case_id"],
                "symbol": case["symbol"],
                "trade_date": case["trade_date"],
                "horizon": case["horizon"],
                "missing_baseline": baseline is None,
                "missing_candidate": candidate is None,
            }
            missing_cases.append(missing)
            case_diffs.append({"case_id": case["case_id"], "status": "missing", **missing})
            continue
        case_diffs.append(_diff_case(ledger, case, baseline, candidate))

    valid_diffs = [diff for diff in case_diffs if diff.get("status") == "compared"]
    return {
        "comparison_id": _comparison_id(suite.get("suite_id"), baseline_filter, candidate_filter),
        "suite_id": suite.get("suite_id"),
        "generated_at": utc_now_iso(),
        "baseline_filter": baseline_filter,
        "candidate_filter": candidate_filter,
        "summary": {
            "cases": len(suite.get("cases") or []),
            "compared": len(valid_diffs),
            "missing": len(missing_cases),
            "action_changed": sum(1 for diff in valid_diffs if diff.get("action_changed")),
            "confidence_changed": sum(1 for diff in valid_diffs if diff.get("confidence_changed")),
            "quality_status_changed": sum(1 for diff in valid_diffs if diff.get("quality_status_changed")),
            "resolved_reward_pairs": sum(1 for diff in valid_diffs if diff.get("reward_delta") is not None),
        },
        "case_diffs": case_diffs,
        "missing_cases": missing_cases,
        "recommended_debug_queries": [
            "python -m cli.main retrieval-pack --type risk_review --run-id <run_id> --format json",
            "python -m cli.main quality-index --run-id <run_id> --format json",
        ],
    }


def _select_run_for_case(
    ledger: EpisodeLedger,
    case: dict[str, Any],
    variant_filter: dict[str, Any],
    *,
    include_high_leakage: bool,
) -> dict[str, Any] | None:
    filters = {
        "symbol": case["symbol"],
        "horizon": case["horizon"],
        "status": "completed",
        "since": case["trade_date"],
        "until": case["trade_date"],
        "include_high_leakage": include_high_leakage,
        **{key: value for key, value in variant_filter.items() if value},
    }
    rows = ledger.list_run_index(filters)
    return rows[0] if rows else None


def _diff_case(
    ledger: EpisodeLedger,
    case: dict[str, Any],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    baseline_conf = _confidence_number(baseline.get("confidence"))
    candidate_conf = _confidence_number(candidate.get("confidence"))
    baseline_reward = _latest_reward(ledger, baseline.get("run_id"))
    candidate_reward = _latest_reward(ledger, candidate.get("run_id"))
    reward_delta = None
    if baseline_reward and candidate_reward:
        left = baseline_reward.get("reward_scalar")
        right = candidate_reward.get("reward_scalar")
        if left is not None and right is not None:
            reward_delta = float(right) - float(left)
    return {
        "case_id": case["case_id"],
        "status": "compared",
        "symbol": case["symbol"],
        "trade_date": case["trade_date"],
        "horizon": case["horizon"],
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "baseline_action": baseline.get("final_action"),
        "candidate_action": candidate.get("final_action"),
        "action_changed": baseline.get("final_action") != candidate.get("final_action"),
        "baseline_confidence": baseline.get("confidence"),
        "candidate_confidence": candidate.get("confidence"),
        "confidence_changed": baseline.get("confidence") != candidate.get("confidence"),
        "confidence_delta": (
            candidate_conf - baseline_conf
            if baseline_conf is not None and candidate_conf is not None
            else None
        ),
        "advisory_rating_changed": baseline.get("advisory_rating") != candidate.get("advisory_rating"),
        "baseline_quality_status": baseline.get("quality_status"),
        "candidate_quality_status": candidate.get("quality_status"),
        "quality_status_changed": baseline.get("quality_status") != candidate.get("quality_status"),
        "critical_failure_delta": len(candidate.get("critical_failures") or [])
        - len(baseline.get("critical_failures") or []),
        "stale_source_delta": len(candidate.get("stale_sources") or [])
        - len(baseline.get("stale_sources") or []),
        "reward_delta": reward_delta,
        "artifact_refs": [
            baseline.get("audit_ref"),
            candidate.get("audit_ref"),
            baseline.get("quality_index_ref"),
            candidate.get("quality_index_ref"),
        ],
    }


def _confidence_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    aliases = {"low": 0.25, "medium": 0.5, "moderate": 0.5, "high": 0.75}
    if text in aliases:
        return aliases[text]
    try:
        return float(text.strip("%")) / (100.0 if text.endswith("%") else 1.0)
    except ValueError:
        return None


def _latest_reward(ledger: EpisodeLedger, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    episode = ledger.load_episode(str(run_id))
    rewards = (episode or {}).get("rewards") or []
    return rewards[-1] if rewards else None


def _comparison_id(
    suite_id: Any,
    baseline_filter: dict[str, Any],
    candidate_filter: dict[str, Any],
) -> str:
    baseline = "_".join(f"{key}-{value}" for key, value in sorted(baseline_filter.items()) if value)
    candidate = "_".join(f"{key}-{value}" for key, value in sorted(candidate_filter.items()) if value)
    safe_suite = str(suite_id or "suite").replace(":", "_")
    return f"prompt_regression:{safe_suite}:{baseline or 'baseline'}_vs_{candidate or 'candidate'}"

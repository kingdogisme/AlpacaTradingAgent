from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .indexing import build_quality_index, build_run_index
from .ledger import EpisodeLedger, git_provenance, trust_tier_for


STRICT_MISSING_TIMESTAMP_DATASETS = {
    "filings",
    "macro_news",
    "news",
    "price_bars",
    "social",
    "technical_indicators",
}


def run_pit_case(
    *,
    symbol: str,
    trade_date: str,
    horizon: str,
    config: dict[str, Any],
    strict: bool = True,
) -> dict[str, Any]:
    cfg = dict(config)
    cfg["trading_horizon"] = horizon
    cfg["online_tools"] = False if strict else bool(cfg.get("online_tools", False))
    cfg["historical_mode"] = "strict" if strict else cfg.get("historical_mode", "permissive")
    cfg["run_policy"] = "pit_strict" if strict else "current_pit_rerun"
    cfg["data_cutoff"] = trade_date
    cfg["episode_ledger_metadata"] = {
        **(cfg.get("episode_ledger_metadata") or {}),
        "data_leakage_risk": "low",
        "run_policy": cfg["run_policy"],
        "data_cutoff": trade_date,
        "source": "pit_run",
        **git_provenance(),
    }
    analysts = cfg.get("selected_analysts") or ["market", "social", "news", "fundamentals", "macro"]
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(selected_analysts=analysts, config=cfg, debug=False)
    final_state, final_signal = graph.propagate(symbol, trade_date)
    run_id = getattr(graph, "last_run_id", None)
    audit = audit_pit_run(EpisodeLedger(cfg.get("episode_ledger_path")), run_id=run_id, strict=strict) if run_id else None
    return {
        "run_id": run_id,
        "symbol": symbol.upper(),
        "trade_date": trade_date,
        "horizon": horizon,
        "final_signal": final_signal,
        "pit_audit": audit,
        "final_state_keys": sorted(final_state.keys()) if isinstance(final_state, dict) else [],
    }


def audit_pit_run(ledger: EpisodeLedger, *, run_id: str, strict: bool = True) -> dict[str, Any]:
    run_index = build_run_index(ledger, run_id)
    quality_rows = build_quality_index(ledger, run_id)
    episode = ledger.load_episode(run_id) or {}
    experiment = episode.get("experiment") or {}
    metadata = episode.get("metadata") or {}
    leakage_counts = Counter(row.get("leakage_status") or "unknown" for row in quality_rows)
    unverifiable = [
        row
        for row in quality_rows
        if row.get("leakage_status") == "unverifiable"
        and str(row.get("dataset_type") or "") in STRICT_MISSING_TIMESTAMP_DATASETS
    ]
    leaks = [row for row in quality_rows if row.get("leakage_status") == "leak"]
    live_only = [
        row
        for row in quality_rows
        if _is_live_only_tool(row.get("tool_name")) or _is_live_only_source(row.get("source_id"))
    ]
    high_leakage = bool(leaks or (strict and (unverifiable or live_only)))
    leakage_risk = "high" if high_leakage else str(experiment.get("leakage_risk") or metadata.get("data_leakage_risk") or "low")
    status = "fail" if high_leakage else "pass"
    return {
        "run_id": run_id,
        "status": status,
        "strict": strict,
        "trust_tier": trust_tier_for(experiment.get("run_policy"), leakage_risk),
        "leakage_risk": leakage_risk,
        "trade_date": episode.get("trade_date"),
        "provenance": {
            "system_version": experiment.get("system_version"),
            "git_commit": experiment.get("git_commit"),
            "dirty_diff_hash": experiment.get("dirty_diff_hash"),
            "prompt_version": experiment.get("prompt_version"),
            "config_hash": experiment.get("config_hash"),
            "model_provider": experiment.get("model_provider"),
            "quick_model": experiment.get("quick_model"),
            "deep_model": experiment.get("deep_model"),
            "run_policy": experiment.get("run_policy"),
            "data_snapshot_id": experiment.get("data_snapshot_id"),
            "run_started_at": experiment.get("run_started_at"),
        },
        "summary": {
            "tool_events": len(quality_rows),
            "leakage_status_distribution": dict(leakage_counts),
            "leak_count": len(leaks),
            "unverifiable_strict_count": len(unverifiable),
            "live_only_count": len(live_only),
            "quality_status": (run_index or {}).get("quality_status"),
        },
        "violations": [_compact_quality_row(row) for row in [*leaks, *unverifiable, *live_only]],
        "recommended_action": "exclude_from_main_benchmark" if high_leakage else "eligible_for_current_pit_rerun",
    }


def _compact_quality_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_ref": row.get("artifact_ref"),
        "tool_name": row.get("tool_name"),
        "source_id": row.get("source_id"),
        "dataset_type": row.get("dataset_type"),
        "observed_at": row.get("observed_at"),
        "requested_trade_date": row.get("requested_trade_date"),
        "leakage_status": row.get("leakage_status"),
        "flags": row.get("flags") or [],
    }


def _is_live_only_tool(tool_name: object) -> bool:
    text = str(tool_name or "").lower()
    return any(token in text for token in ("openai", "latest", "live", "web_search"))


def _is_live_only_source(source_id: object) -> bool:
    text = str(source_id or "").lower()
    return text.startswith("openai_") or "live" in text


def parse_suite_cases(path: str | Path) -> list[dict[str, Any]]:
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    cases: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_cases or [], start=1):
        symbol = item.get("symbol") or item.get("ticker")
        trade_date = item.get("date") or item.get("trade_date")
        horizon = item.get("horizon") or "swing"
        if symbol and trade_date:
            cases.append({"case_id": item.get("case_id") or f"case-{idx}", "symbol": symbol, "date": trade_date, "horizon": horizon})
    return cases

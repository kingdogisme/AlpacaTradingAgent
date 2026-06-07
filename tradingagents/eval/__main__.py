from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .benchmarking import compare_existing_runs, load_benchmark_suite
from .critic import DEFAULT_CRITIC_VERSION, HeuristicCritic, critic_memory_candidate
from .export import export_jsonl
from .harness import build_harness_report, build_hypothesis_report
from .ledger import EpisodeLedger
from .memory_v2 import (
    create_data_quality_memory_candidates,
    create_memory_candidates_from_critic,
    demote_memory,
    memory_ablation as build_memory_ablation,
    memory_report as build_memory_report,
    normalize_legacy_memory_items,
    promote_memory,
    retrieve_memory,
)
from .pit import audit_pit_run, parse_suite_cases, run_pit_case
from .reporting import soft_gate_audit as build_soft_gate_audit, summarize_rows
from .rewards import RewardResolver
from .targets import (
    EvaluationTargetBuilder,
    TargetAwareRewardResolver,
    build_target_report,
)


app = typer.Typer(help="TradingAgents evaluation ledger and reward tooling.")
console = Console()


def _load_config(path: Optional[Path]) -> dict:
    config = DEFAULT_CONFIG.copy()
    if path:
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


@app.command()
def collect(
    symbols: str = typer.Option(..., help="Comma-separated symbols, e.g. AAPL,MSFT"),
    dates: str = typer.Option(..., help="Comma-separated analysis dates, YYYY-MM-DD"),
    config: Optional[Path] = typer.Option(None, help="JSON config override path"),
    allow_live_web_data: bool = typer.Option(False, help="Allow current web/news tools during historical collect."),
) -> None:
    cfg = _load_config(config)
    cfg["online_tools"] = bool(allow_live_web_data)
    metadata_risk = "high" if allow_live_web_data else "low"
    cfg["episode_ledger_metadata"] = {"data_leakage_risk": metadata_risk, "source": "eval_collect"}
    analysts = cfg.get("selected_analysts") or ["market", "social", "news", "fundamentals", "macro"]
    for symbol in [item.strip() for item in symbols.split(",") if item.strip()]:
        graph = TradingAgentsGraph(selected_analysts=analysts, config=cfg, debug=False)
        for trade_date in [item.strip() for item in dates.split(",") if item.strip()]:
            console.print(f"[eval] collecting {symbol} {trade_date} leakage={metadata_risk}")
            graph.propagate(symbol, trade_date)


@app.command()
def score(
    as_of: str = typer.Option(..., help="Resolve rewards as of YYYY-MM-DD."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    resolver = RewardResolver(ledger, config=DEFAULT_CONFIG)
    rewards = resolver.score_due_episodes(as_of=as_of)
    console.print(f"Resolved {len(rewards)} reward(s).")


@app.command("eval-target-build")
def eval_target_build(
    since: Optional[str] = typer.Option(None, help="Only build episode targets since YYYY-MM-DD."),
    include_trade_plans: bool = typer.Option(True, help="Include trade lifecycle conditional targets."),
    include_ad_candidates: bool = typer.Option(True, help="Include AlphaDiscovery candidate targets."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
    trade_db_path: Optional[Path] = typer.Option(None, help="Override trade lifecycle SQLite path."),
    ad_db_path: Optional[Path] = typer.Option(None, help="Override AlphaDiscovery SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    trade_repository = None
    alpha_repository = None
    if include_trade_plans:
        from tradingagents.trade_lifecycle import TradePlanRepository

        trade_repository = TradePlanRepository(trade_db_path or DEFAULT_CONFIG.get("trade_lifecycle_db_path"))
    if include_ad_candidates:
        from tradingagents.alpha_discovery import AlphaDiscoveryRepository

        alpha_repository = AlphaDiscoveryRepository(ad_db_path or DEFAULT_CONFIG.get("alpha_discovery_db_path"))
    targets = EvaluationTargetBuilder(
        ledger,
        trade_repository=trade_repository,
        alpha_repository=alpha_repository,
        config=DEFAULT_CONFIG,
    ).build_all(since=since)
    console.print_json(data={"created_or_updated": len(targets), "target_ids": [target.target_id for target in targets]})


@app.command("eval-target-list")
def eval_target_list(
    target_type: Optional[str] = typer.Option(None, help="Filter by target type."),
    symbol: Optional[str] = typer.Option(None, help="Filter by symbol."),
    horizon: Optional[str] = typer.Option(None, help="Filter by horizon."),
    pending_only: bool = typer.Option(False, help="Only targets missing the current reward version outcome."),
    limit: Optional[int] = typer.Option(100, help="Maximum targets to print."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    rows = ledger.list_evaluation_targets(
        {
            "target_type": target_type,
            "symbol": symbol.upper() if symbol else None,
            "horizon": horizon,
            "pending_only": pending_only,
            "reward_version": DEFAULT_CONFIG.get("eval_reward_version", "v1_directional_alpha"),
            "limit": limit,
        }
    )
    console.print_json(data=rows)


@app.command("eval-target-resolve")
def eval_target_resolve(
    as_of: str = typer.Option(..., help="Resolve targets as of YYYY-MM-DD."),
    target_type: Optional[str] = typer.Option(None, help="Filter by target type."),
    symbol: Optional[str] = typer.Option(None, help="Filter by symbol."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    outcomes = TargetAwareRewardResolver(ledger, config=DEFAULT_CONFIG).score_due_targets(
        as_of=as_of,
        filters={"target_type": target_type, "symbol": symbol.upper() if symbol else None},
    )
    console.print_json(data={"resolved": len(outcomes), "target_ids": [outcome.target_id for outcome in outcomes]})


@app.command("eval-target-report")
def eval_target_report(
    group_by: str = typer.Option("trust_tier,system_version,prompt_version,config_hash,target_type,horizon,symbol", help="Comma-separated grouping fields."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage targets/outcomes."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    groups = [item.strip() for item in group_by.split(",") if item.strip()]
    console.print_json(data=build_target_report(ledger, group_by=groups, include_high_leakage=include_high_leakage))


@app.command("pit-run")
def pit_run(
    symbol: str = typer.Option(..., help="Ticker to rerun point-in-time."),
    date: str = typer.Option(..., help="Historical trade date YYYY-MM-DD."),
    horizon: str = typer.Option("swing", help="Trading horizon: swing, position, or trend."),
    strict: bool = typer.Option(True, help="Disable online tools and require PIT-safe inputs."),
    config: Optional[Path] = typer.Option(None, help="JSON config override path."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    payload = run_pit_case(symbol=symbol, trade_date=date, horizon=horizon, config=_load_config(config), strict=strict)
    console.print_json(data=payload)


@app.command("pit-audit")
def pit_audit(
    run_id: str = typer.Option(..., help="Run id to audit for point-in-time leakage."),
    strict: bool = typer.Option(True, help="Treat unverifiable timestamps as leakage violations."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    console.print_json(data=audit_pit_run(EpisodeLedger(ledger_path), run_id=run_id, strict=strict))


@app.command("pit-benchmark")
def pit_benchmark(
    suite: Path = typer.Option(..., help="Benchmark suite JSON path."),
    strict: bool = typer.Option(True, help="Run every case in strict historical mode."),
    config: Optional[Path] = typer.Option(None, help="JSON config override path."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    cfg = _load_config(config)
    results = [
        {"case_id": case["case_id"], **run_pit_case(symbol=case["symbol"], trade_date=case["date"], horizon=case["horizon"], config=cfg, strict=strict)}
        for case in parse_suite_cases(suite)
    ]
    console.print_json(
        data={
            "suite": str(suite),
            "strict": strict,
            "case_count": len(results),
            "eligible_count": sum(1 for item in results if (item.get("pit_audit") or {}).get("status") == "pass"),
            "results": results,
        }
    )


@app.command("normalize-traces")
def normalize_traces(
    since: Optional[str] = typer.Option(None, help="Only normalize episodes since YYYY-MM-DD."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    total = 0
    for episode in ledger.list_episodes({"since": since, "status": "completed"} if since else {"status": "completed"}):
        total += len(ledger.normalize_trace(episode.run_id))
    console.print(f"Normalized {total} trace span(s).")


@app.command()
def critique(
    run_id: Optional[str] = typer.Option(None, help="Critique a single run ID."),
    due_only: bool = typer.Option(False, help="Critique resolved-reward episodes without this critic version."),
    critic_version: str = typer.Option(DEFAULT_CRITIC_VERSION, help="Critic version identifier."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    critic = HeuristicCritic(critic_version=critic_version)
    episodes = []
    if run_id:
        episode = ledger.load_episode(run_id)
        if episode:
            episodes.append(episode)
    elif due_only:
        episodes = ledger.resolved_reward_episodes_without_critic(critic_version)
    else:
        raise typer.BadParameter("Pass --run-id or --due-only.")

    created = 0
    for episode in episodes:
        if not any(reward.get("reward_status", "resolved") == "resolved" for reward in episode.get("rewards", [])):
            continue
        record = critic.critique(episode)
        ledger.add_critic_record(record)
        ledger.add_memory_item(critic_memory_candidate(record))
        created += 1
    console.print(f"Created {created} critic record(s).")


@app.command()
def report(
    since: Optional[str] = typer.Option(None, help="Only include episodes since YYYY-MM-DD."),
    group_by: str = typer.Option("model,horizon,symbol", help="Comma-separated grouping fields."),
    include_high_leakage: bool = typer.Option(False, help="Include episodes collected with live web/news data."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    rows = ledger.report_rows(since=since, include_high_leakage=include_high_leakage)
    groups = [item.strip() for item in group_by.split(",") if item.strip()]
    summaries = summarize_rows(rows, groups)

    table = Table(title="TradingAgents Eval Report")
    for column in [
        "group",
        "episodes",
        "resolved",
        "pending",
        "hit_rate",
        "avg_raw_return",
        "avg_alpha",
        "avg_reward",
        "trace_cov",
        "memory_candidates",
    ]:
        table.add_column(column)
    for summary in summaries:
        table.add_row(
            json.dumps(summary["group"], sort_keys=True),
            str(summary["episodes"]),
            str(summary["resolved"]),
            str(summary["pending"]),
            _fmt(summary["hit_rate"]),
            _fmt(summary["avg_raw_return"]),
            _fmt(summary["avg_alpha"]),
            _fmt(summary["avg_reward"]),
            _fmt(summary["trace_coverage_rate"]),
            str(summary["memory_candidate_count"]),
        )
    console.print(table)
    console.print_json(data=summaries)


@app.command("soft-gate-audit")
def soft_gate_audit(
    since: Optional[str] = typer.Option(None, help="Only include episodes since YYYY-MM-DD."),
    include_high_leakage: bool = typer.Option(False, help="Include episodes collected with live web/news data."),
    format: str = typer.Option("json", help="Output format: json or table."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    rows = ledger.report_rows(since=since, include_high_leakage=include_high_leakage)
    payload = build_soft_gate_audit(rows)
    if format == "json":
        console.print_json(data=payload)
        return
    if format != "table":
        raise typer.BadParameter("format must be table or json")
    table = Table(title="Soft Gate Audit")
    table.add_column("metric")
    table.add_column("value")
    for key, value in payload.items():
        table.add_row(key, json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value))
    console.print(table)


@app.command("harness-report")
def harness_report(
    suite: Optional[Path] = typer.Option(None, help="Benchmark suite JSON path."),
    since: Optional[str] = typer.Option(None, help="Only include episodes since YYYY-MM-DD."),
    prompt_version: Optional[str] = typer.Option(None, help="Filter by prompt version."),
    config_hash: Optional[str] = typer.Option(None, help="Filter by config hash."),
    experiment_id: Optional[str] = typer.Option(None, help="Filter by experiment id."),
    baseline_prompt: Optional[str] = typer.Option(None, help="Baseline prompt version for suite comparison."),
    candidate_prompt: Optional[str] = typer.Option(None, help="Candidate prompt version for suite comparison."),
    baseline_config_hash: Optional[str] = typer.Option(None, help="Baseline config hash for suite comparison."),
    candidate_config_hash: Optional[str] = typer.Option(None, help="Candidate config hash for suite comparison."),
    baseline_experiment: Optional[str] = typer.Option(None, help="Baseline experiment id for suite comparison."),
    candidate_experiment: Optional[str] = typer.Option(None, help="Candidate experiment id for suite comparison."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage episodes."),
    min_resolved: int = typer.Option(5, help="Minimum resolved sample for hypothesis conclusions."),
    format: str = typer.Option("json", help="Output format: json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    ledger = EpisodeLedger(ledger_path)
    payload = build_harness_report(
        ledger,
        suite_path=suite,
        since=since,
        include_high_leakage=include_high_leakage,
        variant_filter={
            "prompt_version": prompt_version,
            "config_hash": config_hash,
            "experiment_id": experiment_id,
        },
        baseline_filter={
            "prompt_version": baseline_prompt,
            "config_hash": baseline_config_hash,
            "experiment_id": baseline_experiment,
        },
        candidate_filter={
            "prompt_version": candidate_prompt,
            "config_hash": candidate_config_hash,
            "experiment_id": candidate_experiment,
        },
        min_resolved=min_resolved,
    )
    console.print_json(data=payload)


@app.command("hypothesis-report")
def hypothesis_report(
    since: Optional[str] = typer.Option(None, help="Only include episodes since YYYY-MM-DD."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage episodes."),
    min_resolved: int = typer.Option(5, help="Minimum resolved sample for hypothesis conclusions."),
    format: str = typer.Option("json", help="Output format: json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    ledger = EpisodeLedger(ledger_path)
    payload = build_hypothesis_report(
        ledger,
        since=since,
        include_high_leakage=include_high_leakage,
        min_resolved=min_resolved,
    )
    console.print_json(data=payload)


@app.command()
def export(
    format: str = typer.Option("jsonl", help="Export format. Only jsonl is supported in v1.5."),
    since: Optional[str] = typer.Option(None, help="Only export episodes since YYYY-MM-DD."),
    output: Optional[Path] = typer.Option(None, help="Output JSONL path. Defaults to stdout."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage episodes."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    if format != "jsonl":
        raise typer.BadParameter("Only --format jsonl is supported.")
    ledger = EpisodeLedger(ledger_path)
    count = export_jsonl(
        ledger,
        since=since,
        output_path=output,
        include_high_leakage=include_high_leakage,
    )
    if output:
        console.print(f"Exported {count} JSONL record(s) to {output}.")


@app.command("compare-prompts")
def compare_prompts(
    suite_path: Path = typer.Option(..., help="Benchmark suite JSON path."),
    baseline_prompt: Optional[str] = typer.Option(None, help="Baseline prompt version."),
    candidate_prompt: Optional[str] = typer.Option(None, help="Candidate prompt version."),
    baseline_config_hash: Optional[str] = typer.Option(None, help="Baseline config hash."),
    candidate_config_hash: Optional[str] = typer.Option(None, help="Candidate config hash."),
    baseline_experiment: Optional[str] = typer.Option(None, help="Baseline experiment id."),
    candidate_experiment: Optional[str] = typer.Option(None, help="Candidate experiment id."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage runs."),
    strict: bool = typer.Option(False, help="Exit non-zero when any suite case is missing."),
    format: str = typer.Option("table", help="Output format: table or json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    """Compare existing indexed runs for a fixed benchmark suite."""
    baseline_filter = {
        "prompt_version": baseline_prompt,
        "config_hash": baseline_config_hash,
        "experiment_id": baseline_experiment,
    }
    candidate_filter = {
        "prompt_version": candidate_prompt,
        "config_hash": candidate_config_hash,
        "experiment_id": candidate_experiment,
    }
    if not any(baseline_filter.values()) or not any(candidate_filter.values()):
        raise typer.BadParameter("Provide at least one baseline and one candidate filter.")
    ledger = EpisodeLedger(ledger_path)
    suite = load_benchmark_suite(suite_path)
    result = compare_existing_runs(
        ledger,
        suite,
        baseline_filter=baseline_filter,
        candidate_filter=candidate_filter,
        include_high_leakage=include_high_leakage,
    )
    if format == "json":
        console.print_json(data=result)
    elif format == "table":
        table = Table(title=f"Prompt Regression: {result['suite_id']}")
        for column in (
            "case",
            "status",
            "baseline",
            "candidate",
            "action",
            "confidence_delta",
            "quality",
            "reward_delta",
        ):
            table.add_column(column)
        for diff in result["case_diffs"]:
            table.add_row(
                str(diff.get("case_id")),
                str(diff.get("status")),
                str(diff.get("baseline_run_id") or ("missing" if diff.get("missing_baseline") else "")),
                str(diff.get("candidate_run_id") or ("missing" if diff.get("missing_candidate") else "")),
                f"{diff.get('baseline_action')} -> {diff.get('candidate_action')}"
                if diff.get("status") == "compared"
                else "-",
                _fmt(diff.get("confidence_delta")),
                f"{diff.get('baseline_quality_status')} -> {diff.get('candidate_quality_status')}"
                if diff.get("status") == "compared"
                else "-",
                _fmt(diff.get("reward_delta")),
            )
        console.print(table)
        console.print_json(data=result["summary"])
    else:
        raise typer.BadParameter("format must be table or json")
    if strict and result["missing_cases"]:
        raise typer.Exit(1)


@app.command("memory-candidates")
def memory_candidates(
    run_id: Optional[str] = typer.Option(None, help="Run id to create/list candidates for."),
    since: Optional[str] = typer.Option(None, help="Only scan episodes since YYYY-MM-DD."),
    due_only: bool = typer.Option(False, help="Only resolved episodes missing critic output."),
    include_data_quality: bool = typer.Option(True, help="Create data-quality candidates for --run-id."),
    format: str = typer.Option("table", help="Output format: table or json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    normalize_legacy_memory_items(ledger)
    created = create_memory_candidates_from_critic(
        ledger,
        run_id=run_id,
        since=since,
        due_only=due_only,
    )
    if run_id and include_data_quality:
        created.extend(create_data_quality_memory_candidates(ledger, run_id))
    payload = {
        "summary": {"created": len(created)},
        "items": created,
        "artifact_refs": [ref for item in created for ref in (item.get("supporting_refs") or []) if ref],
        "recommended_debug_queries": [
            "python -m tradingagents.eval memory-retrieve --run-id <run_id> --stage risk_manager --policy ticker_horizon_promoted_v1 --format json"
        ],
    }
    if format == "json":
        console.print_json(data=payload)
        return
    if format != "table":
        raise typer.BadParameter("format must be table or json")
    table = Table(title="Memory Candidates")
    for column in ("memory_id", "state", "type", "symbol", "horizon"):
        table.add_column(column)
    for item in created:
        table.add_row(
            str(item.get("memory_id")),
            str(item.get("state")),
            str(item.get("memory_type")),
            str(item.get("symbol") or ""),
            str(item.get("horizon") or ""),
        )
    console.print(table)


@app.command("memory-retrieve")
def memory_retrieve(
    run_id: str = typer.Option(..., help="Run id requesting memory."),
    stage: str = typer.Option(..., help="Agent/stage using retrieved memory."),
    policy: str = typer.Option("ticker_horizon_promoted_v1", help="Retrieval policy."),
    limit: int = typer.Option(5, help="Maximum memories to retrieve."),
    format: str = typer.Option("json", help="Output format: json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    ledger = EpisodeLedger(ledger_path)
    payload = retrieve_memory(ledger, run_id=run_id, stage=stage, policy=policy, limit=limit)
    console.print_json(data=payload)


@app.command("memory-promote")
def memory_promote(
    memory_id: str = typer.Option(..., help="Memory id to promote."),
    reason: str = typer.Option(..., help="Promotion reason."),
    promoted_by: str = typer.Option("user", help="Actor promoting this memory."),
    allow_manual: bool = typer.Option(False, help="Allow promotion without resolved reward."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    item = promote_memory(
        ledger,
        memory_id=memory_id,
        reason=reason,
        promoted_by=promoted_by,
        allow_manual=allow_manual,
    )
    console.print_json(data=item)


@app.command("memory-demote")
def memory_demote(
    memory_id: str = typer.Option(..., help="Memory id to demote."),
    reason: str = typer.Option(..., help="Demotion reason."),
    demoted_by: str = typer.Option("user", help="Actor demoting this memory."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    item = demote_memory(ledger, memory_id=memory_id, reason=reason, demoted_by=demoted_by)
    console.print_json(data=item)


@app.command("memory-report")
def memory_report(
    symbol: Optional[str] = typer.Option(None, help="Symbol filter."),
    horizon: Optional[str] = typer.Option(None, help="Horizon filter."),
    format: str = typer.Option("table", help="Output format: table or json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    ledger = EpisodeLedger(ledger_path)
    payload = build_memory_report(ledger, symbol=symbol, horizon=horizon)
    if format == "json":
        console.print_json(data=payload)
        return
    if format != "table":
        raise typer.BadParameter("format must be table or json")
    table = Table(title="Memory Report")
    table.add_column("metric")
    table.add_column("value")
    for key, value in payload["summary"].items():
        table.add_row(key, json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value))
    console.print(table)


@app.command("memory-ablation")
def memory_ablation(
    since: Optional[str] = typer.Option(None, help="Only include episodes since YYYY-MM-DD."),
    policies: str = typer.Option("none,ticker_horizon_promoted_v1,data_quality_lessons_v1", help="Comma-separated policies."),
    format: str = typer.Option("json", help="Output format: json."),
    ledger_path: Optional[Path] = typer.Option(None, help="Override ledger SQLite path."),
) -> None:
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    ledger = EpisodeLedger(ledger_path)
    payload = build_memory_ablation(
        ledger,
        since=since,
        policies=[item.strip() for item in policies.split(",") if item.strip()],
    )
    console.print_json(data=payload)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    app()

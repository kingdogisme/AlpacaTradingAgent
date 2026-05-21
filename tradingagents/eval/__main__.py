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
from .ledger import EpisodeLedger
from .reporting import summarize_rows
from .rewards import RewardResolver


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


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    app()

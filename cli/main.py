from __future__ import annotations

import json
import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

import cli.legacy_main as legacy_main
from tradingagents.alpha_discovery import AlphaDiscoveryService
from tradingagents.alpha_discovery.reporting import compact_candidate, count_values
from cli.legacy_main import *  # noqa: F401,F403 - preserve historical cli.main imports
from cli.legacy_main import (
    DEFAULT_CONFIG,
    _ad_print,
    _record_ad_handoff_for_ticker,
    _AtaV2Runner,
    _TradingAgentsGraphRunner,
    analyze,
    cron_discover,
    cron_confirm,
    cron_run,
    ata_run,
    ata_report,
    ata_decide,
    trade_monitor,
    trade_plan_list,
    trade_plan_show,
    trade_plan_events,
    trade_plan_health,
    trade_monitor_status,
    trade_monitor_preflight,
    trade_plan_reconcile,
    trade_plan_action,
    cron_resolve,
    basket_list,
    basket_report,
    basket_eval_report,
    eval_target_build,
    eval_target_list,
    eval_target_resolve,
    eval_target_report,
    pit_run,
    pit_audit,
    pit_benchmark,
    ad_events,
    ad_health,
    ad_ingest,
    cron_schedule,
    run_index,
    buy_runs,
    quality_index,
    quality_reconcile,
    source_reliability,
    retrieval_pack,
    quality_summary,
    quality_events,
    quality_open,
)

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Auditable Multi-Agent Trading Research Framework",
    add_completion=True,
)


def get_user_selections():
    """Compatibility wrapper that keeps monkeypatches on cli.main effective."""
    for name in (
        "get_ticker",
        "select_analysts",
        "select_research_depth",
        "select_trading_horizon",
        "select_trend_execution_enabled",
        "select_llm_provider",
        "get_backend_url",
        "select_shallow_thinking_agent",
        "select_deep_thinking_agent",
        "ask_gemini_thinking_config",
        "ask_anthropic_effort",
        "select_checkpoint_enabled",
        "get_output_language",
        "console",
    ):
        if name in globals():
            setattr(legacy_main, name, globals()[name])
    return legacy_main.get_user_selections()


def cron_run(
    tier: str = typer.Option("A", help="Basket tier to run."),
    max_symbols: int = typer.Option(6, help="Maximum symbols to inspect or execute."),
    execute: bool = typer.Option(
        False,
        help="Actually call ATA V2 report+decision. A-list executes automatically when enabled in config.",
    ),
    dry_run: bool = typer.Option(False, help="Force dry-run even when A-list auto-run is enabled."),
    legacy_graph: bool = typer.Option(
        False,
        "--legacy-graph",
        help="Use the pre-V2 monolithic TradingAgentsGraph for ATA handoff.",
    ),
    trade_date: str = typer.Option(
        datetime.date.today().isoformat(),
        help="ATA trade date in YYYY-MM-DD format.",
    ),
    ticker: str = typer.Option(None, help="Optional ticker filter for manual AD handoff runs."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    should_execute = execute or (
        not dry_run
        and tier.upper() == "A"
        and bool(DEFAULT_CONFIG.get("alpha_discovery_auto_run_a_list", True))
    )
    runner_cls = _TradingAgentsGraphRunner if legacy_graph else _AtaV2Runner
    runner = runner_cls(DEFAULT_CONFIG.copy()) if should_execute else None
    results = service.run_candidates(
        tier=tier,
        max_symbols=max_symbols,
        execute=should_execute,
        trade_date=trade_date,
        graph_runner=runner,
        ticker=ticker,
    )
    _ad_print(
        "cron_run",
        {
            "tier": tier,
            "execute": should_execute,
            "auto_run_a_list": bool(DEFAULT_CONFIG.get("alpha_discovery_auto_run_a_list", True)),
            "dry_run": dry_run,
            "runner": "legacy_graph" if legacy_graph else "ata_v2",
            "result_count": len(results),
            "run_status_counts": count_values(results, "run_status"),
            "candidates": [compact_candidate(row) for row in results],
        },
    )


def _agent_map_payload() -> dict:
    return {
        "generated_for": "ai_agent_navigation",
        "rules": [
            "Start with indexes and retrieval packs before opening raw audit JSON.",
            "Preserve historical imports from tradingagents.dataflows.interface and cli.main.",
            "Treat eval_results*, logs, caches, .venv, and __pycache__ as local artifacts, not source.",
        ],
        "module_entrypoints": {
            "dataflows": {
                "public_import": "tradingagents.dataflows.interface",
                "groups": {
                    "news": "tradingagents.dataflows.interface.news",
                    "fundamentals": "tradingagents.dataflows.interface.fundamentals",
                    "market_data": "tradingagents.dataflows.interface.market_data",
                    "technical": "tradingagents.dataflows.interface.technical",
                    "macro": "tradingagents.dataflows.interface.macro",
                },
            },
            "cli": {
                "public_app": "cli.main:app",
                "groups": {
                    "run": "cli.commands.run",
                    "alpha_discovery": "cli.commands.alpha",
                    "eval_targets": "cli.commands.eval",
                    "trade_lifecycle": "cli.commands.trade_lifecycle",
                    "quality": "cli.commands.quality",
                },
            },
            "eval_ledger": {
                "public_class": "tradingagents.eval.ledger.EpisodeLedger",
                "support_modules": [
                    "tradingagents.eval.ledger_schema",
                    "tradingagents.eval.ledger_records",
                    "tradingagents.eval.ledger_trace",
                ],
            },
            "agent_tools": {
                "public_import": "tradingagents.agents.utils.agent_utils",
                "quality_helpers": "tradingagents.agents.utils.tool_quality",
            },
            "v2_contracts": {
                "public_import": "tradingagents.contracts",
                "groups": {
                    "research": "tradingagents.contracts.research",
                    "decision": "tradingagents.contracts.decision",
                    "execution": "tradingagents.contracts.execution",
                    "eval": "tradingagents.contracts.eval",
                },
            },
            "v2_layers": {
                "research": "tradingagents.research.service.ResearchService",
                "portfolio_decision": "tradingagents.portfolio.service.PortfolioDecisionService",
                "execution": "tradingagents.execution.service.ExecutionService",
            },
        },
        "core_commands": [
            "python -m cli.main ata-report --ticker <ticker> --trade-date <date> --horizon <horizon>",
            "python -m cli.main ata-decide --report-id <report_id>",
            "python -m cli.main run-index --run-id <run_id> --format json",
            "python -m cli.main quality-index --run-id <run_id> --format json",
            "python -m cli.main pit-audit --run-id <run_id> --format json",
            "python -m cli.main retrieval-pack --type risk_review --run-id <run_id> --format json",
            "python -m cli.main retrieval-pack --type layer_eval --layer decision --artifact-id <decision_id> --format json",
            "python -m cli.main quality-open --run-id <run_id> --artifact-ref <ref> --no-include-output",
        ],
        "test_commands": [
            "python3 -m pytest tests/unit/dataflows",
            "python3 -m pytest tests/unit/cli",
            "python3 -m pytest tests/unit/eval",
            "python3 -m pytest tests/unit/agents",
            "python3 -m pytest tests/unit/webui tests/integration/mocked/test_webui_dash_smoke.py",
        ],
        "artifact_locations": {
            "run_audits": "eval_results/<symbol>/TradingAgentsStrategy_logs/runs/",
            "eval_ledger_default": "~/.tradingagents/eval/agent_eval.sqlite",
            "data_cache": "tradingagents/dataflows/data_cache/",
            "logs": "logs/",
        },
        "recommended_debug_path": ["run-index", "quality-index", "retrieval-pack", "raw audit excerpt"],
        "grep_hints": [
            "rg -n \"def <name>|class <name>\" tradingagents cli webui tests",
            "rg -n \"@app.command|agent-map|run-index\" cli",
            "rg -n \"quality_details|artifact_ref|trace_spans\" tradingagents tests",
        ],
    }


@app.command("agent-map")
def agent_map(
    format: str = typer.Option("json", help="Output format: json or table."),
) -> None:
    """Print compact repo navigation metadata for AI coding agents."""
    payload = _agent_map_payload()
    if format == "json":
        console.print_json(data=payload)
        return
    if format != "table":
        raise typer.BadParameter("format must be json or table")
    console.print("Recommended debug path: " + " -> ".join(payload["recommended_debug_path"]))
    console.print("Core commands:")
    for command in payload["core_commands"]:
        console.print(f"- {command}")


for command_name, callback in [
    ("cron-discover", cron_discover),
    ("cron-confirm", cron_confirm),
    ("cron-run", cron_run),
    ("ata-run", ata_run),
    ("ata-report", ata_report),
    ("ata-decide", ata_decide),
    ("trade-monitor", trade_monitor),
    ("trade-plan-list", trade_plan_list),
    ("trade-plan-show", trade_plan_show),
    ("trade-plan-events", trade_plan_events),
    ("trade-plan-health", trade_plan_health),
    ("trade-monitor-status", trade_monitor_status),
    ("trade-monitor-preflight", trade_monitor_preflight),
    ("trade-plan-reconcile", trade_plan_reconcile),
    ("trade-plan-action", trade_plan_action),
    ("cron-resolve", cron_resolve),
    ("basket-list", basket_list),
    ("basket-report", basket_report),
    ("basket-eval-report", basket_eval_report),
    ("eval-target-build", eval_target_build),
    ("eval-target-list", eval_target_list),
    ("eval-target-resolve", eval_target_resolve),
    ("eval-target-report", eval_target_report),
    ("pit-run", pit_run),
    ("pit-audit", pit_audit),
    ("pit-benchmark", pit_benchmark),
    ("ad-events", ad_events),
    ("ad-health", ad_health),
    ("ad-ingest", ad_ingest),
    ("cron-schedule", cron_schedule),
    ("run-index", run_index),
    ("buy-runs", buy_runs),
    ("quality-index", quality_index),
    ("quality-reconcile", quality_reconcile),
    ("source-reliability", source_reliability),
    ("retrieval-pack", retrieval_pack),
    ("quality-summary", quality_summary),
    ("quality-events", quality_events),
    ("quality-open", quality_open),
]:
    app.command(command_name)(callback)

app.command()(analyze)


if __name__ == "__main__":
    app()

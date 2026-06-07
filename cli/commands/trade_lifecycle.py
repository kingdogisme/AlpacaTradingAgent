"""Command group compatibility exports.

Implementation currently lives in `cli.legacy_main`; this module gives agents a
smaller map of ownership without changing the public CLI contract.
"""

import json
from typing import Optional

import typer

from tradingagents.default_config import DEFAULT_CONFIG

from cli.legacy_main import (
    trade_monitor, trade_plan_list, trade_plan_show, trade_plan_events, trade_plan_health, trade_monitor_status, trade_monitor_preflight, trade_plan_reconcile, trade_plan_action,
)
from cli.commands.robinhood import robinhood_login, robinhood_probe


def trade_plan_execute(
    plan_id: str = typer.Option(..., help="Trade plan id."),
    broker: Optional[str] = typer.Option(None, help="Broker adapter to use, e.g. alpaca or robinhood."),
    dry_run: bool = typer.Option(True, "--dry-run/--submit-order", help="Review only by default; --submit-order allows broker order submission."),
    db_path: Optional[str] = typer.Option(None, help="Optional trade lifecycle SQLite path."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    """Execute a reviewed trade plan through the configured broker router."""
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    from tradingagents.execution import TradePlanExecutionService
    from tradingagents.trade_lifecycle import TradePlanRepository, summarize_plan

    config = DEFAULT_CONFIG.copy()
    if db_path:
        config["trade_lifecycle_db_path"] = db_path
    repository = TradePlanRepository(config.get("trade_lifecycle_db_path"))
    result = TradePlanExecutionService(config=config, repository=repository).execute_plan(
        plan_id,
        broker_name=broker,
        dry_run=dry_run,
    )
    plan = repository.get_plan(plan_id)
    payload = {
        "execution": result.model_dump(mode="json"),
        "plan": summarize_plan(plan, repository) if plan else None,
        "dry_run": dry_run,
        "broker": broker or config.get("broker_adapter"),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


__all__ = [
    'trade_monitor',
    'trade_plan_list',
    'trade_plan_show',
    'trade_plan_events',
    'trade_plan_health',
    'trade_monitor_status',
    'trade_monitor_preflight',
    'trade_plan_reconcile',
    'trade_plan_action',
    'trade_plan_execute',
    'robinhood_login',
    'robinhood_probe',
]

from typing import Optional
import json
import datetime
import re
import typer
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.columns import Columns
from rich.markdown import Markdown
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich.table import Table
from collections import deque
import time
from rich.tree import Tree
from rich import box
from rich.align import Align
from rich.rule import Rule
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.run_logger import get_run_audit_logger
from tradingagents.dataflows.data_quality import (
    find_audit_path,
    load_audit_payload,
    open_artifact_from_audit,
    quality_events_from_audit,
    summarize_quality_events,
)
from tradingagents.eval.indexing import (
    build_quality_index,
    build_retrieval_pack,
    build_run_index,
    rebuild_run_indexes,
    utc_now_iso,
)
from tradingagents.alpha_discovery import AlphaDiscoveryRepository, AlphaDiscoveryService
from tradingagents.alpha_discovery.models import Handoff
from tradingagents.alpha_discovery.reporting import compact_candidate, compact_event, count_values, json_envelope
from cli.models import AnalystType
from cli.utils import *

console = Console()


def _ad_print(kind: str, payload: dict | list) -> None:
    console.print_json(json_envelope(kind, payload))


def _safe_ledger(config):
    if not config.get("episode_ledger_enabled", True):
        return None
    try:
        from tradingagents.eval import EpisodeLedger

        return EpisodeLedger(config.get("episode_ledger_path"))
    except Exception as exc:
        console.print(f"[yellow][EVAL] Episode ledger unavailable: {exc}[/yellow]")
        return None


def _ledger_start(ledger, run_id, ticker, trade_date, config, analysts, metadata):
    if not ledger or not run_id:
        return
    try:
        episode_metadata = {
            "data_leakage_risk": "high" if config.get("online_tools", True) else "low",
            **metadata,
            **(config.get("episode_ledger_metadata") or {}),
        }
        ledger.start_episode(
            run_id=run_id,
            symbol=ticker,
            trade_date=str(trade_date),
            config=config,
            selected_analysts=analysts,
            metadata=episode_metadata,
        )
    except Exception as exc:
        console.print(f"[yellow][EVAL] Failed to start episode ledger entry: {exc}[/yellow]")


def _ledger_complete(ledger, run_id, final_state, final_signal, audit_path):
    if not ledger or not run_id:
        return
    try:
        ledger.complete_episode(run_id, final_state, final_signal, audit_path)
    except Exception as exc:
        console.print(f"[yellow][EVAL] Failed to complete episode ledger entry: {exc}[/yellow]")


def _ledger_fail(ledger, run_id, error_message):
    if not ledger or not run_id:
        return
    try:
        ledger.fail_episode(run_id, error_message)
    except Exception as exc:
        console.print(f"[yellow][EVAL] Failed to mark episode failure: {exc}[/yellow]")


def _resolve_audit_payload(
    *,
    run_id: str | None = None,
    audit_path: str | None = None,
) -> tuple[dict, Path]:
    if audit_path:
        path = Path(audit_path).expanduser()
    elif run_id:
        found = find_audit_path(run_id)
        if not found:
            raise typer.BadParameter(f"Could not find audit log for run_id={run_id}")
        path = found
    else:
        raise typer.BadParameter("Provide --run-id or --audit-path")
    if not path.exists():
        raise typer.BadParameter(f"Audit path does not exist: {path}")
    return load_audit_payload(path), path


def _quality_summary_from_payload(audit: dict) -> dict:
    events = quality_events_from_audit(audit)
    return summarize_quality_events(
        events,
        run_id=audit.get("run_id"),
        symbol=audit.get("symbol"),
        trade_date=audit.get("trade_date"),
    )


def _index_envelope(records: list[dict], *, summary: dict | None = None) -> dict:
    return {
        "generated_at": utc_now_iso(),
        "summary": summary or {"records": len(records)},
        "records": records,
        "artifact_refs": [
            item.get("audit_ref") or item.get("artifact_ref")
            for item in records
            if item.get("audit_ref") or item.get("artifact_ref")
        ],
        "recommended_debug_queries": [
            "python -m cli.main retrieval-pack --type risk_review --run-id <run_id> --format json",
            "python -m cli.main quality-index --run-id <run_id> --format json",
        ],
    }

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Auditable Multi-Agent Trading Research Framework",
    add_completion=True,  # Enable shell completion
)


class _TradingAgentsGraphRunner:
    def __init__(self, config: dict):
        self.config = config

    def run(self, ticker: str, trade_date: str, analysts: list[str]):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph(selected_analysts=analysts, config=self.config, debug=False)
        final_state, final_signal = graph.propagate(ticker, trade_date)
        run_id = getattr(graph, "last_run_id", None)
        audit_logger = get_run_audit_logger()
        run_id = run_id or audit_logger.get_active_run_id(symbol=ticker)
        if not run_id:
            audit_path = audit_logger.get_run_file_path(symbol=ticker)
            if audit_path:
                run_id = Path(str(audit_path)).stem
        confidence = None
        final_text = str(final_state.get("final_trade_decision", "") if isinstance(final_state, dict) else "")
        confidence_match = re.search(r"confidence\**\s*:\s*([A-Za-z]+)", final_text, flags=re.IGNORECASE)
        if confidence_match:
            confidence = confidence_match.group(1)
        return run_id, final_signal, confidence


def _record_ad_handoff_for_ticker(
    *,
    ticker: str,
    run_id: str | None,
    final_signal: str | None,
    confidence: str | None,
    config: dict,
) -> str | None:
    if not run_id:
        return None
    try:
        repository = AlphaDiscoveryRepository(config.get("alpha_discovery_db_path"))
        candidates = repository.list_candidates(
            tiers=["A", "B", "C", "Rejected"],
            status="open",
            limit=1,
            ticker=ticker,
        )
        if not candidates:
            return None
        candidate = candidates[0]
        repository.upsert_handoff(
            Handoff(
                candidate_id=candidate["candidate_id"],
                run_id=run_id,
                status="completed" if final_signal else "unknown",
                executed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ata_final_signal=final_signal,
                ata_confidence=confidence,
            )
        )
        return candidate["candidate_id"]
    except Exception as exc:
        console.print(f"[yellow][AD] Failed to record ticker handoff: {exc}[/yellow]")
        return None


@app.command("cron-discover")
def cron_discover(
    source: str = typer.Option("wsb,dd", help="Comma-separated sources: wsb,dd."),
    max_candidates: int = typer.Option(25, help="Maximum candidates to persist."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    sources = [part.strip().lower() for part in source.split(",") if part.strip()]
    summary = service.discover(sources=sources, max_candidates=max_candidates)
    _ad_print(
        "cron_discover",
        {
            "batch_id": summary["batch_id"],
            "raw_discoveries": summary["raw_discoveries"],
            "tier_counts": summary["tier_counts"],
            "top_rejection_reasons": summary["top_rejection_reasons"],
            "top_candidates": [
                {
                    "ticker": candidate.ticker,
                    "tier": candidate.tier,
                    "alpha_score": candidate.alpha_score,
                    "promotion_gate": (candidate.score_components or {}).get("promotion_gate"),
                    "confirmation_sources": (candidate.score_components or {}).get("confirmation_sources", []),
                    "risk_flags": candidate.risk_flags,
                }
                for candidate in summary.get("candidates", [])[:10]
            ],
        },
    )


@app.command("cron-confirm")
def cron_confirm(
    tier: str = typer.Option("B,C", help="Comma-separated tiers to re-check for promotion."),
    max_candidates: int = typer.Option(25, help="Maximum open candidates to re-confirm."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    tiers = [part.strip() for part in tier.split(",") if part.strip()]
    _ad_print("cron_confirm", service.promote_existing(tiers=tiers, max_candidates=max_candidates))


@app.command("cron-run")
def cron_run(
    tier: str = typer.Option("A", help="Basket tier to run."),
    max_symbols: int = typer.Option(6, help="Maximum symbols to inspect or execute."),
    execute: bool = typer.Option(False, help="Actually call ATA. Default is dry-run."),
    trade_date: str = typer.Option(
        datetime.date.today().isoformat(),
        help="ATA trade date in YYYY-MM-DD format.",
    ),
    ticker: str = typer.Option(None, help="Optional ticker filter for manual AD handoff runs."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    runner = _TradingAgentsGraphRunner(DEFAULT_CONFIG.copy()) if execute else None
    results = service.run_candidates(
        tier=tier,
        max_symbols=max_symbols,
        execute=execute,
        trade_date=trade_date,
        graph_runner=runner,
        ticker=ticker,
    )
    _ad_print(
        "cron_run",
        {
            "tier": tier,
            "execute": execute,
            "result_count": len(results),
            "run_status_counts": count_values(results, "run_status"),
            "candidates": [compact_candidate(row) for row in results],
        },
    )


@app.command("ata-run")
def ata_run(
    ticker: str = typer.Argument(..., help="Ticker to analyze."),
    trade_date: str = typer.Option(
        datetime.date.today().isoformat(),
        help="ATA trade date in YYYY-MM-DD format.",
    ),
    horizon: str = typer.Option(
        "position",
        help="Trading horizon: swing, position, or trend. Position means 1-3 months.",
    ),
    analysts: str = typer.Option(
        "market,fundamentals,news,social,macro",
        help="Comma-separated analysts.",
    ),
    record_ad_handoff: bool = typer.Option(
        True,
        help="Link the run to the latest open AD candidate for this ticker when present.",
    ),
) -> None:
    config = DEFAULT_CONFIG.copy()
    config["trading_horizon"] = horizon
    config["trading_mode"] = "investment"
    selected_analysts = [part.strip() for part in analysts.split(",") if part.strip()]
    runner = _TradingAgentsGraphRunner(config)
    run_id, final_signal, confidence = runner.run(ticker.upper(), trade_date, selected_analysts)
    candidate_id = (
        _record_ad_handoff_for_ticker(
            ticker=ticker.upper(),
            run_id=run_id,
            final_signal=final_signal,
            confidence=confidence,
            config=config,
        )
        if record_ad_handoff
        else None
    )
    _ad_print(
        "ata_run",
        {
            "ticker": ticker.upper(),
            "trade_date": trade_date,
            "horizon": horizon,
            "analysts": selected_analysts,
            "run_id": run_id,
            "final_signal": final_signal,
            "confidence": confidence,
            "ad_candidate_id": candidate_id,
        },
    )


@app.command("cron-resolve")
def cron_resolve(
    as_of: str = typer.Option(..., help="Resolve candidate outcomes as of YYYY-MM-DD."),
) -> None:
    from tradingagents.alpha_discovery.outcomes import OutcomeResolver

    repository = AlphaDiscoveryRepository(DEFAULT_CONFIG.get("alpha_discovery_db_path"))
    outcomes = OutcomeResolver(repository, config=DEFAULT_CONFIG).resolve_open_candidates(as_of=as_of)
    _ad_print("cron_resolve", [outcome.__dict__ for outcome in outcomes])


@app.command("basket-list")
def basket_list(
    tier: str = typer.Option("A,B", help="Comma-separated tiers, e.g. A,B,C,Rejected."),
    status: str = typer.Option("open", help="Candidate status filter."),
    limit: int = typer.Option(25, help="Maximum rows to print."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    tiers = [part.strip() for part in tier.split(",") if part.strip()]
    rows = service.list_candidates(tiers=tiers, status=status, limit=limit)
    _ad_print("basket_list", [compact_candidate(row) for row in rows])


@app.command("basket-report")
def basket_report(
    status: str = typer.Option("open", help="Candidate status filter."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    _ad_print("basket_report", service.basket_report(status=status))


@app.command("basket-eval-report")
def basket_eval_report(
    status: str = typer.Option("open", help="Candidate status filter."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    _ad_print("basket_eval_report", service.evaluation_report(status=status))


@app.command("ad-events")
def ad_events(
    batch_id: str = typer.Option(None, help="Filter by discovery/confirmation batch id."),
    candidate_id: str = typer.Option(None, help="Filter by candidate id."),
    event_type: str = typer.Option(None, help="Filter by event type."),
    status: str = typer.Option(None, help="Filter by event status."),
    limit: int = typer.Option(100, help="Maximum events to print."),
) -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    _ad_print(
        "ad_events",
        [
            compact_event(row)
            for row in service.list_events(
                batch_id=batch_id,
                candidate_id=candidate_id,
                event_type=event_type,
                status=status,
                limit=limit,
            )
        ],
    )


@app.command("ad-health")
def ad_health() -> None:
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    _ad_print("ad_health", service.health_report())


@app.command("ad-ingest")
def ad_ingest(
    file: str = typer.Option(..., help="JSON file containing external watchlist candidates."),
    source: str = typer.Option("n8n_watchlist", help="Logical source name for the ingest batch."),
    max_candidates: int = typer.Option(25, help="Maximum candidates to persist after scoring/dedup."),
) -> None:
    payload = json.loads(Path(file).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        candidates = payload.get("candidates") or payload.get("items") or payload.get("data") or []
    elif isinstance(payload, list):
        candidates = payload
    else:
        raise typer.BadParameter("JSON payload must be a list or an object containing candidates/items/data.")
    if not isinstance(candidates, list):
        raise typer.BadParameter("Resolved candidate payload must be a list.")
    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    summary = service.ingest_external_candidates(
        candidates,
        source=source,
        max_candidates=max_candidates,
    )
    _ad_print(
        "ad_ingest",
        {
            "batch_id": summary["batch_id"],
            "source": summary["source"],
            "accepted": summary["accepted"],
            "skipped": summary["skipped"],
            "tickers": summary["tickers"],
            "tier_counts": summary["tier_counts"],
        },
    )


@app.command("cron-schedule")
def cron_schedule() -> None:
    """Print cron-friendly Alpha Discovery windows in America/New_York time."""
    console.print_json(
        json.dumps(
            {
                "timezone": "America/New_York",
                "discovery_windows": [
                    {"time": "08:15", "purpose": "daily premarket discovery rebuild"},
                    {"time": "15:30", "purpose": "optional late-day discovery only when live-news/volume shock is active"},
                    {"time": "20:00", "purpose": "evening DD/news refresh for next session"},
                ],
                "confirmation_windows": [
                    {"time": "09:25", "purpose": "pre-open confirmation pass"},
                    {"time": "16:30", "purpose": "post-close confirmation pass"},
                ],
                "full_ata_windows": ["09:30", "16:45"],
                "default_daily_ata_budget": DEFAULT_CONFIG.get("alpha_discovery_default_ata_daily_budget", 5),
                "same_ticker_cooldown_hours": DEFAULT_CONFIG.get("alpha_discovery_full_ata_cooldown_hours", 24),
                "commands": {
                    "discover": "python -m cli.main cron-discover --source wsb,dd --max-candidates 25",
                    "confirm": "python -m cli.main cron-confirm --tier B,C --max-candidates 25",
                    "dry_run": "python -m cli.main cron-run --tier A --max-symbols 6",
                    "execute": "python -m cli.main cron-run --tier A --max-symbols 6 --execute",
                    "resolve": "python -m cli.main cron-resolve --as-of YYYY-MM-DD",
                    "evaluate": "python -m cli.main basket-eval-report --status open",
                    "events": "python -m cli.main ad-events --limit 100",
                    "health": "python -m cli.main ad-health",
                    "ingest": "python -m cli.main ad-ingest --file /path/to/candidates.json --source n8n_watchlist --max-candidates 25",
                },
            },
            ensure_ascii=False,
        )
    )


# Create a deque to store recent messages with a maximum length
class MessageBuffer:
    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None  # Store the complete final report
        self.agent_status = {
            # Analyst Team
            "Market Analyst": "pending",
            "Social Analyst": "pending",
            "News Analyst": "pending",
            "Fundamentals Analyst": "pending",
            "Macro Analyst": "pending",
            # Research Team
            "Bull Researcher": "pending",
            "Bear Researcher": "pending",
            "Research Manager": "pending",
            # Trading Team
            "Trader": "pending",
            # Risk Management Team
            "Risky Analyst": "pending",
            "Neutral Analyst": "pending",
            "Safe Analyst": "pending",
            # Portfolio Management Team
            "Portfolio Manager": "pending",
        }
        self.current_agent = None
        self.report_sections = {
            "market_report": None,
            "sentiment_report": None,
            "news_report": None,
            "fundamentals_report": None,
            "macro_report": None,
            "investment_plan": None,
            "trader_investment_plan": None,
            "final_trade_decision": None,
        }

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        # For the panel display, only show the most recently updated section
        latest_section = None
        latest_content = None

        # Find the most recently updated section
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content

        if latest_section and latest_content:
            # Format the current section for display
            section_titles = {
                "market_report": "Market Analysis",
                "sentiment_report": "Social Sentiment",
                "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "macro_report": "Macro Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
            }
            self.current_report = (
                f"### {section_titles[latest_section]}\n{latest_content}"
            )

        # Update the final complete report
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        # Analyst Team Reports
        if any(
            self.report_sections[section]
            for section in [
                "market_report",
                "sentiment_report",
                "news_report",
                "fundamentals_report",
                "macro_report",
            ]
        ):
            report_parts.append("## Analyst Team Reports")
            if self.report_sections["market_report"]:
                report_parts.append(
                    f"### Market Analysis\n{self.report_sections['market_report']}"
                )
            if self.report_sections["sentiment_report"]:
                report_parts.append(
                    f"### Social Sentiment\n{self.report_sections['sentiment_report']}"
                )
            if self.report_sections["news_report"]:
                report_parts.append(
                    f"### News Analysis\n{self.report_sections['news_report']}"
                )
            if self.report_sections["fundamentals_report"]:
                report_parts.append(
                    f"### Fundamentals Analysis\n{self.report_sections['fundamentals_report']}"
                )
            if self.report_sections["macro_report"]:
                report_parts.append(
                    f"### Macro Analysis\n{self.report_sections['macro_report']}"
                )

        # Research Team Reports
        if self.report_sections["investment_plan"]:
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")

        # Trading Team Reports
        if self.report_sections["trader_investment_plan"]:
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")

        # Portfolio Management Decision
        if self.report_sections["final_trade_decision"]:
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")

        self.final_report = "\n\n".join(report_parts) if report_parts else None


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", ratio=3), Layout(name="analysis", ratio=5)
    )
    layout["upper"].split_row(
        Layout(name="progress", ratio=2), Layout(name="messages", ratio=3)
    )
    return layout


def update_display(layout, spinner_text=None):
    # Header with welcome message
    layout["header"].update(
        Panel(
            "[bold green]Welcome to AlpacaTradingAgent CLI[/bold green]\n"
            "[dim]Auditable multi-agent trading research framework[/dim]\n"
            "[dim]© [Tauric Research](https://github.com/TauricResearch)[/dim]",
            title="Welcome to AlpacaTradingAgent",
            border_style="green",
            padding=(1, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("Agent", style="green", justify="center", width=20)
    progress_table.add_column("Status", style="yellow", justify="center", width=20)

    # Group agents by team
    teams = {
        "Analyst Team": [
            "Market Analyst",
            "Social Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Risky Analyst", "Neutral Analyst", "Safe Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status[first_agent]
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]in_progress[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{status}[/{status_color}]"
        progress_table.add_row(team, first_agent, status_cell)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status[agent]
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]in_progress[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{status}[/{status_color}]"
            progress_table.add_row("", agent, status_cell)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("Time", style="cyan", width=8, justify="center")
    messages_table.add_column("Type", style="green", width=10, justify="center")
    messages_table.add_column(
        "Content", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    for timestamp, tool_name, args in message_buffer.tool_calls:
        # Truncate tool call args if too long
        if isinstance(args, str) and len(args) > 100:
            args = args[:97] + "..."
        all_messages.append((timestamp, "Tool", f"{tool_name}: {args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        # Truncate message content if too long
        if isinstance(content, str) and len(content) > 200:
            content = content[:197] + "..."
        all_messages.append((timestamp, msg_type, content))

    # Sort by timestamp
    all_messages.sort(key=lambda x: x[0])

    # Calculate how many messages we can show based on available space
    # Start with a reasonable number and adjust based on content length
    max_messages = 12  # Increased from 8 to better fill the space

    # Get the last N messages that will fit in the panel
    recent_messages = all_messages[-max_messages:]

    # Add messages to table
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    if spinner_text:
        messages_table.add_row("", "Spinner", spinner_text)

    # Add a footer to indicate if messages were truncated
    if len(all_messages) > max_messages:
        messages_table.footer = (
            f"[dim]Showing last {max_messages} of {len(all_messages)} messages[/dim]"
        )

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel showing current report
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]Waiting for analysis report...[/italic]",
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )

    # Footer with statistics
    tool_calls_count = len(message_buffer.tool_calls)
    llm_calls_count = sum(
        1 for _, msg_type, _ in message_buffer.messages if msg_type == "Reasoning"
    )
    reports_count = sum(
        1 for content in message_buffer.report_sections.values() if content is not None
    )

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(
        f"Tool Calls: {tool_calls_count} | LLM Calls: {llm_calls_count} | Generated Reports: {reports_count}"
    )

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections():
    """Get user selections for analysis."""
    # Display ASCII art welcome message
    with open("./cli/static/welcome.txt", "r", encoding="utf-8") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]AlpacaTradingAgent: Auditable Multi-Agent Trading Research Framework - CLI[/bold green]\n\n"
    welcome_content += "[bold]Workflow Steps:[/bold]\n"
    welcome_content += "I. Analyst Team → II. Research Team → III. Trader → IV. Risk Management → V. Portfolio Management\n\n"
    welcome_content += (
        "[dim]Built by [Tauric Research](https://github.com/TauricResearch)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="Welcome to AlpacaTradingAgent",
        subtitle="Paper trading, strategy testing, and risk-controlled execution",
    )
    console.print(Align.center(welcome_box))
    console.print()  # Add a blank line after the welcome box

    def create_question_box(title, prompt, default=None):
        lines = [
            "┌─────────────────────────────────────────────────────────────────────────────────┐",
            f"│ {title:<79} │",
            "├─────────────────────────────────────────────────────────────────────────────────┤",
            f"│ {prompt:<79} │",
        ]
        if default:
            lines.append(f"│ {'Default: ' + default:<79} │")
        lines.append(
            "└─────────────────────────────────────────────────────────────────────────────────┘"
        )
        return "\n".join(lines)

    # Step 1: Ticker symbol
    console.print(
        create_question_box(
            "Step 1: Ticker Symbol", "Enter the ticker symbol", "SPY"
        )
    )
    selected_ticker = get_ticker()

    # Step 2: Use current date for real-time analysis
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        f"[green]Using current date for real-time analysis:[/green] {current_date}"
    )

    # Step 3: Select analysts
    console.print(
        create_question_box(
            "Step 3: Analysts Team", "Select your LLM analyst agents for the analysis"
        )
    )
    selected_analysts = select_analysts()
    console.print(
        f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 4: Research depth
    console.print(
        create_question_box(
            "Step 4: Research Depth", "Select your research depth level"
        )
    )
    selected_research_depth = select_research_depth()

    # Step 5: Trading horizon
    console.print(
        create_question_box(
            "Step 5: Trading Horizon", "Select holding period and analysis focus", "Swing"
        )
    )
    selected_trading_horizon = select_trading_horizon()
    selected_trend_execution_enabled = False
    if selected_trading_horizon in {"position", "trend"}:
        console.print(
            create_question_box(
                "Step 5a: Trend Execution",
                "Select whether non-swing runs should use execution-enabled semantics in prompts and logging. CLI remains analysis-only.",
                "Disabled",
            )
        )
        selected_trend_execution_enabled = select_trend_execution_enabled()

    # Step 6: Thinking agents
    console.print(
        create_question_box(
            "Step 6: Thinking Agents", "Select your thinking agents for analysis"
        )
    )
    selected_llm_provider = select_llm_provider()
    backend_url = get_backend_url() if selected_llm_provider in {
        "local_openai",
        "ollama",
        "openrouter",
        "azure",
        "xai",
        "deepseek",
        "qwen",
        "glm",
    } else ""
    selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
    selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)
    google_thinking_level = ask_gemini_thinking_config() if selected_llm_provider == "google" else ""
    anthropic_effort = ask_anthropic_effort() if selected_llm_provider == "anthropic" else ""
    checkpoint_enabled = select_checkpoint_enabled()
    output_language = get_output_language()

    return {
        "ticker": selected_ticker,
        "analysis_date": current_date,  # Always use current date
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "trading_horizon": selected_trading_horizon,
        "trend_execution_enabled": selected_trend_execution_enabled,
        "llm_provider": selected_llm_provider,
        "backend_url": backend_url,
        "checkpoint_enabled": checkpoint_enabled,
        "output_language": output_language,
        "google_thinking_level": google_thinking_level,
        "anthropic_effort": anthropic_effort,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
    }


def get_ticker():
    """Get ticker symbol from user input."""
    return typer.prompt("", default="SPY")


def display_complete_report(final_state):
    """Display the complete analysis report with team-based panels."""
    console.print("\n[bold green]Complete Analysis Report[/bold green]\n")

    # I. Analyst Team Reports
    analyst_reports = []

    # Market Analyst Report
    if final_state.get("market_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["market_report"]),
                title="Market Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # Social Analyst Report
    if final_state.get("sentiment_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["sentiment_report"]),
                title="Social Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # News Analyst Report
    if final_state.get("news_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["news_report"]),
                title="News Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # Fundamentals Analyst Report
    if final_state.get("fundamentals_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["fundamentals_report"]),
                title="Fundamentals Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # Macro Analyst Report
    if final_state.get("macro_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["macro_report"]),
                title="Macro Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    if analyst_reports:
        console.print(
            Panel(
                Columns(analyst_reports, equal=True, expand=True),
                title="I. Analyst Team Reports",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    # II. Research Team Reports
    if final_state.get("investment_debate_state"):
        research_reports = []
        debate_state = final_state["investment_debate_state"]

        # Bull Researcher Analysis
        if debate_state.get("bull_history"):
            research_reports.append(
                Panel(
                    Markdown(debate_state["bull_history"]),
                    title="Bull Researcher",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Bear Researcher Analysis
        if debate_state.get("bear_history"):
            research_reports.append(
                Panel(
                    Markdown(debate_state["bear_history"]),
                    title="Bear Researcher",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Research Manager Decision
        if debate_state.get("judge_decision"):
            research_reports.append(
                Panel(
                    Markdown(debate_state["judge_decision"]),
                    title="Research Manager",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        if research_reports:
            console.print(
                Panel(
                    Columns(research_reports, equal=True, expand=True),
                    title="II. Research Team Decision",
                    border_style="magenta",
                    padding=(1, 2),
                )
            )

    # III. Trading Team Reports
    if final_state.get("trader_investment_plan"):
        console.print(
            Panel(
                Panel(
                    Markdown(final_state["trader_investment_plan"]),
                    title="Trader",
                    border_style="blue",
                    padding=(1, 2),
                ),
                title="III. Trading Team Plan",
                border_style="yellow",
                padding=(1, 2),
            )
        )

    # IV. Risk Management Team Reports
    if final_state.get("risk_debate_state"):
        risk_reports = []
        risk_state = final_state["risk_debate_state"]

        # Aggressive (Risky) Analyst Analysis
        if risk_state.get("risky_history"):
            risk_reports.append(
                Panel(
                    Markdown(risk_state["risky_history"]),
                    title="Aggressive Analyst",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Conservative (Safe) Analyst Analysis
        if risk_state.get("safe_history"):
            risk_reports.append(
                Panel(
                    Markdown(risk_state["safe_history"]),
                    title="Conservative Analyst",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Neutral Analyst Analysis
        if risk_state.get("neutral_history"):
            risk_reports.append(
                Panel(
                    Markdown(risk_state["neutral_history"]),
                    title="Neutral Analyst",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        if risk_reports:
            console.print(
                Panel(
                    Columns(risk_reports, equal=True, expand=True),
                    title="IV. Risk Management Team Decision",
                    border_style="red",
                    padding=(1, 2),
                )
            )

        # V. Portfolio Manager Decision
        if risk_state.get("judge_decision"):
            console.print(
                Panel(
                    Panel(
                        Markdown(risk_state["judge_decision"]),
                        title="Portfolio Manager",
                        border_style="blue",
                        padding=(1, 2),
                    ),
                    title="V. Portfolio Manager Decision",
                    border_style="green",
                    padding=(1, 2),
                )
            )


def update_research_team_status(status):
    """Update status for all research team members and trader."""
    research_team = ["Bull Researcher", "Bear Researcher", "Research Manager", "Trader"]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)


def run_analysis():
    # First get all user selections
    selections = get_user_selections()

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["llm_provider"] = selections["llm_provider"]
    config["backend_url"] = selections["backend_url"] or None
    config["checkpoint_enabled"] = selections["checkpoint_enabled"]
    config["output_language"] = selections["output_language"]
    config["trading_horizon"] = selections.get("trading_horizon", "swing")
    config["trend_execution_enabled"] = bool(selections.get("trend_execution_enabled", False))
    if selections.get("google_thinking_level"):
        config["google_thinking_level"] = selections["google_thinking_level"]
    if selections.get("anthropic_effort"):
        config["anthropic_effort"] = selections["anthropic_effort"]
    config["trading_mode"] = "investment"

    # Initialize the graph
    graph = TradingAgentsGraph(
        [analyst.value for analyst in selections["analysts"]], config=config, debug=True
    )
    run_logger = get_run_audit_logger()
    run_started = False
    ledger = _safe_ledger(config)
    run_id = None

    # Now start the display layout
    layout = create_layout()

    with Live(layout, refresh_per_second=4) as live:
        # Initial display
        update_display(layout)

        # Add initial messages
        message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
        message_buffer.add_message(
            "System", f"Analysis date: {selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        message_buffer.add_message(
            "System",
            (
                f"Selected horizon: {selections['trading_horizon']}"
                + (
                    " (trend execution semantics enabled; CLI remains analysis-only)"
                    if selections.get("trend_execution_enabled")
                    else " (research-only semantics)"
                )
            ),
        )
        update_display(layout)

        # Reset agent statuses
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "pending")

        # Reset report sections
        for section in message_buffer.report_sections:
            message_buffer.report_sections[section] = None
        message_buffer.current_report = None
        message_buffer.final_report = None

        # Update agent status to in_progress for the first analyst
        first_analyst = f"{selections['analysts'][0].value.capitalize()} Analyst"
        message_buffer.update_agent_status(first_analyst, "in_progress")
        update_display(layout)

        # Create spinner text
        spinner_text = (
            f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text)

        # Initialize state and get graph args
        init_agent_state = graph.propagator.create_initial_state(
            selections["ticker"], selections["analysis_date"]
        )
        graph._resolve_memory_log_outcomes(selections["ticker"], selections["analysis_date"])
        args = graph._graph_args_for_run(selections["ticker"], selections["analysis_date"])
        compiled_graph, checkpointer_ctx = graph._graph_for_run(
            selections["ticker"], selections["analysis_date"]
        )
        run_logger.start_run(
            symbol=selections["ticker"],
            trade_date=str(selections["analysis_date"]),
            config=config,
            metadata={"debug": True, "source": "cli_stream"},
        )
        run_id = run_logger.get_active_run_id(symbol=selections["ticker"])
        _ledger_start(
            ledger,
            run_id,
            selections["ticker"],
            selections["analysis_date"],
            config,
            [analyst.value for analyst in selections["analysts"]],
            {"debug": True, "source": "cli_stream"},
        )
        run_started = True
        run_logger.log_state_snapshot(
            stage="initial_state",
            snapshot=init_agent_state,
            symbol=selections["ticker"],
        )

        # Stream the analysis
        trace = []
        try:
            try:
                graph_stream = compiled_graph.stream(init_agent_state, **args)
                for chunk in graph_stream:
                    if len(chunk["messages"]) > 0:
                        # Get the last message from the chunk
                        last_message = chunk["messages"][-1]

                        # Extract message content and type
                        if hasattr(last_message, "content"):
                            content = last_message.content
                            msg_type = "Reasoning"
                        else:
                            content = str(last_message)
                            msg_type = "System"

                        # Add message to buffer
                        message_buffer.add_message(msg_type, content)

                        # If it's a tool call, add it to tool calls
                        if hasattr(last_message, "tool_calls"):
                            for tool_call in last_message.tool_calls:
                                # Handle both dictionary and object tool calls
                                if isinstance(tool_call, dict):
                                    message_buffer.add_tool_call(
                                        tool_call["name"], tool_call["args"]
                                    )
                                else:
                                    message_buffer.add_tool_call(tool_call.name, tool_call.args)

                        # Update reports and agent status based on chunk content
                        # Analyst Team Reports
                        if "market_report" in chunk and chunk["market_report"]:
                            message_buffer.update_report_section(
                                "market_report", chunk["market_report"]
                            )
                            message_buffer.update_agent_status("Market Analyst", "completed")
                            # Set next analyst to in_progress
                            if "social" in selections["analysts"]:
                                message_buffer.update_agent_status(
                                    "Social Analyst", "in_progress"
                                )

                        if "sentiment_report" in chunk and chunk["sentiment_report"]:
                            message_buffer.update_report_section(
                                "sentiment_report", chunk["sentiment_report"]
                            )
                            message_buffer.update_agent_status("Social Analyst", "completed")
                            # Set next analyst to in_progress
                            if "news" in selections["analysts"]:
                                message_buffer.update_agent_status(
                                    "News Analyst", "in_progress"
                                )

                        if "news_report" in chunk and chunk["news_report"]:
                            message_buffer.update_report_section(
                                "news_report", chunk["news_report"]
                            )
                            message_buffer.update_agent_status("News Analyst", "completed")
                            # Set next analyst to in_progress
                            if "fundamentals" in selections["analysts"]:
                                message_buffer.update_agent_status(
                                    "Fundamentals Analyst", "in_progress"
                                )

                        if "fundamentals_report" in chunk and chunk["fundamentals_report"]:
                            message_buffer.update_report_section(
                                "fundamentals_report", chunk["fundamentals_report"]
                            )
                            message_buffer.update_agent_status(
                                "Fundamentals Analyst", "completed"
                            )
                            if "macro" in selections["analysts"]:
                                message_buffer.update_agent_status(
                                    "Macro Analyst", "in_progress"
                                )

                        if "macro_report" in chunk and chunk["macro_report"]:
                            message_buffer.update_report_section(
                                "macro_report", chunk["macro_report"]
                            )
                            message_buffer.update_agent_status("Macro Analyst", "completed")
                            update_research_team_status("in_progress")

                    # Research Team - Handle Investment Debate State
                    if (
                        "investment_debate_state" in chunk
                        and chunk["investment_debate_state"]
                    ):
                        debate_state = chunk["investment_debate_state"]

                        # Update Bull Researcher status and report
                        if "bull_history" in debate_state and debate_state["bull_history"]:
                            # Keep all research team members in progress
                            update_research_team_status("in_progress")
                            # Extract latest bull response
                            bull_responses = debate_state["bull_history"].split("\n")
                            latest_bull = bull_responses[-1] if bull_responses else ""
                            if latest_bull:
                                message_buffer.add_message("Reasoning", latest_bull)
                                # Update research report with bull's latest analysis
                                message_buffer.update_report_section(
                                    "investment_plan",
                                    f"### Bull Researcher Analysis\n{latest_bull}",
                                )

                        # Update Bear Researcher status and report
                        if "bear_history" in debate_state and debate_state["bear_history"]:
                            # Keep all research team members in progress
                            update_research_team_status("in_progress")
                            # Extract latest bear response
                            bear_responses = debate_state["bear_history"].split("\n")
                            latest_bear = bear_responses[-1] if bear_responses else ""
                            if latest_bear:
                                message_buffer.add_message("Reasoning", latest_bear)
                                # Update research report with bear's latest analysis
                                message_buffer.update_report_section(
                                    "investment_plan",
                                    f"{message_buffer.report_sections['investment_plan']}\n\n### Bear Researcher Analysis\n{latest_bear}",
                                )

                        # Update Research Manager status and final decision
                        if (
                            "judge_decision" in debate_state
                            and debate_state["judge_decision"]
                        ):
                            # Keep all research team members in progress until final decision
                            update_research_team_status("in_progress")
                            message_buffer.add_message(
                                "Reasoning",
                                f"Research Manager: {debate_state['judge_decision']}",
                            )
                            # Update research report with final decision
                            message_buffer.update_report_section(
                                "investment_plan",
                                f"{message_buffer.report_sections['investment_plan']}\n\n### Research Manager Decision\n{debate_state['judge_decision']}",
                            )
                            # Mark all research team members as completed
                            update_research_team_status("completed")
                            # Set first risk analyst to in_progress
                            message_buffer.update_agent_status(
                                "Risky Analyst", "in_progress"
                            )

                    # Trading Team
                    if (
                        "trader_investment_plan" in chunk
                        and chunk["trader_investment_plan"]
                    ):
                        message_buffer.update_report_section(
                            "trader_investment_plan", chunk["trader_investment_plan"]
                        )
                        # Set first risk analyst to in_progress
                        message_buffer.update_agent_status("Risky Analyst", "in_progress")

                    # Risk Management Team - Handle Risk Debate State
                    if "risk_debate_state" in chunk and chunk["risk_debate_state"]:
                        risk_state = chunk["risk_debate_state"]

                        # Update Risky Analyst status and report
                        if (
                            "current_risky_response" in risk_state
                            and risk_state["current_risky_response"]
                        ):
                            message_buffer.update_agent_status(
                                "Risky Analyst", "in_progress"
                            )
                            message_buffer.add_message(
                                "Reasoning",
                                f"Risky Analyst: {risk_state['current_risky_response']}",
                            )
                            # Update risk report with risky analyst's latest analysis only
                            message_buffer.update_report_section(
                                "final_trade_decision",
                                f"### Risky Analyst Analysis\n{risk_state['current_risky_response']}",
                            )

                        # Update Safe Analyst status and report
                        if (
                            "current_safe_response" in risk_state
                            and risk_state["current_safe_response"]
                        ):
                            message_buffer.update_agent_status(
                                "Safe Analyst", "in_progress"
                            )
                            message_buffer.add_message(
                                "Reasoning",
                                f"Safe Analyst: {risk_state['current_safe_response']}",
                            )
                            # Update risk report with safe analyst's latest analysis only
                            message_buffer.update_report_section(
                                "final_trade_decision",
                                f"### Safe Analyst Analysis\n{risk_state['current_safe_response']}",
                            )

                        # Update Neutral Analyst status and report
                        if (
                            "current_neutral_response" in risk_state
                            and risk_state["current_neutral_response"]
                        ):
                            message_buffer.update_agent_status(
                                "Neutral Analyst", "in_progress"
                            )
                            message_buffer.add_message(
                                "Reasoning",
                                f"Neutral Analyst: {risk_state['current_neutral_response']}",
                            )
                            # Update risk report with neutral analyst's latest analysis only
                            message_buffer.update_report_section(
                                "final_trade_decision",
                                f"### Neutral Analyst Analysis\n{risk_state['current_neutral_response']}",
                            )

                        # Update Portfolio Manager status and final decision
                        if "judge_decision" in risk_state and risk_state["judge_decision"]:
                            message_buffer.update_agent_status(
                                "Portfolio Manager", "in_progress"
                            )
                            message_buffer.add_message(
                                "Reasoning",
                                f"Portfolio Manager: {risk_state['judge_decision']}",
                            )
                            # Update risk report with final decision only
                            message_buffer.update_report_section(
                                "final_trade_decision",
                                f"### Portfolio Manager Decision\n{risk_state['judge_decision']}",
                            )
                            # Mark risk analysts as completed
                            message_buffer.update_agent_status("Risky Analyst", "completed")
                            message_buffer.update_agent_status("Safe Analyst", "completed")
                            message_buffer.update_agent_status(
                                "Neutral Analyst", "completed"
                            )
                            message_buffer.update_agent_status(
                                "Portfolio Manager", "completed"
                            )

                        # Update the display
                        update_display(layout)

                    trace.append(chunk)
            finally:
                if checkpointer_ctx is not None:
                    checkpointer_ctx.__exit__(None, None, None)

            # Get final state and decision
            final_state = trace[-1]
            decision = graph.process_signal(final_state["final_trade_decision"])
            graph.curr_state = final_state
            graph.ticker = selections["ticker"]
            graph._log_state(selections["analysis_date"], final_state)
            audit_path = run_logger.get_run_file_path(run_id=run_id, symbol=selections["ticker"])
            run_logger.finish_run(
                symbol=selections["ticker"],
                status="completed",
                final_state=final_state,
                final_signal=decision,
            )
            _ledger_complete(ledger, run_id, final_state, decision, audit_path)
            graph.memory_log.store_decision(
                ticker=selections["ticker"],
                trade_date=selections["analysis_date"],
                final_trade_decision=final_state["final_trade_decision"],
                trading_mode=final_state.get("trading_mode", config.get("trading_mode", "investment")),
                horizon=final_state.get("trading_horizon", config.get("trading_horizon", "swing")),
            )
            if config.get("checkpoint_enabled", False):
                from tradingagents.graph.checkpointer import clear_checkpoint

                clear_checkpoint(
                    config["data_cache_dir"],
                    selections["ticker"],
                    selections["analysis_date"],
                )
            run_started = False
        except Exception as e:
            if run_started:
                _ledger_fail(ledger, run_id, str(e))
                run_logger.finish_run(
                    symbol=selections["ticker"],
                    status="failed",
                    final_state=trace[-1] if trace else None,
                    error_message=str(e),
                )
                run_started = False
            raise

        # Update all agent statuses to completed
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "completed")

        message_buffer.add_message(
            "Analysis", f"Completed analysis for {selections['analysis_date']}"
        )

        # Update final report sections
        for section in message_buffer.report_sections.keys():
            if section in final_state:
                message_buffer.update_report_section(section, final_state[section])

        # Display the complete final report
        display_complete_report(final_state)

        update_display(layout)


@app.command("run-index")
def run_index(
    run_id: Optional[str] = typer.Option(None, help="Run id to rebuild and show."),
    symbol: Optional[str] = typer.Option(None, help="Symbol filter."),
    since: Optional[str] = typer.Option(None, help="Only include trade_date >= YYYY-MM-DD."),
    until: Optional[str] = typer.Option(None, help="Only include trade_date <= YYYY-MM-DD."),
    horizon: Optional[str] = typer.Option(None, help="Horizon filter."),
    prompt_version: Optional[str] = typer.Option(None, help="Prompt version filter."),
    config_hash: Optional[str] = typer.Option(None, help="Config hash filter."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage historical runs."),
    format: str = typer.Option("table", help="Output format: table or json."),
) -> None:
    """Build and query the agent-readable run index."""
    ledger = _safe_ledger(DEFAULT_CONFIG)
    if ledger is None:
        raise typer.BadParameter("Episode ledger unavailable.")
    if run_id:
        build_run_index(ledger, run_id)
    else:
        rebuild_run_indexes(ledger, symbol=symbol, since=since, until=until)
    filters = {
        "run_id": run_id,
        "symbol": symbol,
        "since": since,
        "until": until,
        "horizon": horizon,
        "prompt_version": prompt_version,
        "config_hash": config_hash,
        "include_high_leakage": include_high_leakage,
    }
    records = ledger.list_run_index(filters)
    envelope = _index_envelope(
        records,
        summary={
            "records": len(records),
            "quality_status_distribution": {
                status: sum(1 for item in records if item.get("quality_status") == status)
                for status in ("pass", "warn", "fail", "unknown")
            },
        },
    )
    if format == "json":
        console.print_json(data=envelope)
        return
    if format != "table":
        raise typer.BadParameter("format must be table or json")
    table = Table(title="Run Index", box=box.SIMPLE)
    for column in ("run_id", "symbol", "date", "horizon", "action", "confidence", "quality", "prompt"):
        table.add_column(column)
    for item in records:
        table.add_row(
            str(item.get("run_id")),
            str(item.get("symbol")),
            str(item.get("trade_date")),
            str(item.get("horizon") or ""),
            str(item.get("final_action") or ""),
            str(item.get("confidence") or ""),
            str(item.get("quality_status") or "unknown"),
            str(item.get("prompt_version") or ""),
        )
    console.print(table)


@app.command("quality-index")
def quality_index(
    run_id: str = typer.Option(..., help="Run id to rebuild and show."),
    status: Optional[str] = typer.Option(None, help="Comma-separated statuses to include, e.g. warn,fail."),
    format: str = typer.Option("table", help="Output format: table, json, or jsonl."),
) -> None:
    """Build and query the indexed data-quality events for a run."""
    ledger = _safe_ledger(DEFAULT_CONFIG)
    if ledger is None:
        raise typer.BadParameter("Episode ledger unavailable.")
    build_quality_index(ledger, run_id)
    statuses = [part.strip().lower() for part in status.split(",") if part.strip()] if status else None
    records = ledger.list_quality_index(run_id, statuses=statuses)
    envelope = _index_envelope(
        records,
        summary={
            "run_id": run_id,
            "records": len(records),
            "status_distribution": {
                value: sum(1 for item in records if item.get("status") == value)
                for value in ("pass", "warn", "fail", "unknown")
            },
        },
    )
    if format == "json":
        console.print_json(data=envelope)
        return
    if format == "jsonl":
        for item in records:
            console.print(json.dumps(item, sort_keys=True, ensure_ascii=False))
        return
    if format != "table":
        raise typer.BadParameter("format must be table, json, or jsonl")
    table = Table(title=f"Quality Index: {run_id}", box=box.SIMPLE)
    for column in ("artifact", "tool", "source", "type", "status", "freshness", "flags"):
        table.add_column(column)
    for item in records:
        table.add_row(
            str(item.get("artifact_ref")),
            str(item.get("tool_name") or ""),
            str(item.get("source_id") or ""),
            str(item.get("dataset_type") or ""),
            str(item.get("status") or "unknown"),
            str(item.get("freshness") or "unknown"),
            ",".join(item.get("flags") or []) or "-",
        )
    console.print(table)


@app.command("retrieval-pack")
def retrieval_pack(
    pack_type: str = typer.Option(..., "--type", help="Pack type: risk_review, ticker_horizon, prompt_audit."),
    run_id: Optional[str] = typer.Option(None, help="Run id for risk_review."),
    symbol: Optional[str] = typer.Option(None, help="Symbol for ticker_horizon."),
    horizon: Optional[str] = typer.Option(None, help="Horizon for ticker_horizon."),
    prompt_version: Optional[str] = typer.Option(None, help="Prompt version for prompt_audit."),
    config_hash: Optional[str] = typer.Option(None, help="Config hash for prompt_audit."),
    limit: int = typer.Option(5, help="Maximum indexed runs to include."),
    token_budget: int = typer.Option(4000, help="Approximate token budget."),
    include_high_leakage: bool = typer.Option(False, help="Include high-leakage historical runs."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    """Build a compact retrieval pack for AI-agent or developer debugging."""
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    ledger = _safe_ledger(DEFAULT_CONFIG)
    if ledger is None:
        raise typer.BadParameter("Episode ledger unavailable.")
    payload = build_retrieval_pack(
        ledger,
        pack_type=pack_type,
        run_id=run_id,
        symbol=symbol,
        horizon=horizon,
        prompt_version=prompt_version,
        config_hash=config_hash,
        limit=limit,
        token_budget=token_budget,
        include_high_leakage=include_high_leakage,
    )
    console.print_json(data=payload)


@app.command("quality-summary")
def quality_summary(
    run_id: Optional[str] = typer.Option(None, help="Run id to locate under eval_results."),
    audit_path: Optional[str] = typer.Option(None, help="Path to a run audit JSON file."),
    format: str = typer.Option("table", help="Output format: table or json."),
) -> None:
    """Summarize data quality events for a run audit log."""
    audit, path = _resolve_audit_payload(run_id=run_id, audit_path=audit_path)
    summary = _quality_summary_from_payload(audit)
    summary["audit_path"] = str(path)
    if format == "json":
        console.print_json(data=summary)
        return
    if format != "table":
        raise typer.BadParameter("format must be table or json")

    counts = summary["summary"]
    table = Table(title=f"Data Quality Summary: {summary.get('run_id')}", box=box.SIMPLE)
    table.add_column("Metric")
    table.add_column("Value")
    for key in ("quality_pass", "quality_warn", "quality_fail", "quality_unknown"):
        table.add_row(key, str(counts.get(key, 0)))
    table.add_row("stale_sources", ", ".join(counts.get("stale_sources") or []) or "-")
    table.add_row("fallback_sources", ", ".join(counts.get("fallback_sources") or []) or "-")
    table.add_row("critical_failures", ", ".join(counts.get("critical_failures") or []) or "-")
    table.add_row("audit_path", str(path))
    console.print(table)

    source_table = Table(title="Source Statuses", box=box.SIMPLE)
    source_table.add_column("Source")
    source_table.add_column("Provider")
    source_table.add_column("Type")
    source_table.add_column("Status")
    source_table.add_column("Flags")
    for source in summary.get("source_statuses", []):
        source_table.add_row(
            str(source.get("source_id")),
            str(source.get("provider") or ""),
            str(source.get("dataset_type") or ""),
            str(source.get("status") or "unknown"),
            ",".join(source.get("flags") or []) or "-",
        )
    console.print(source_table)


@app.command("quality-events")
def quality_events(
    run_id: Optional[str] = typer.Option(None, help="Run id to locate under eval_results."),
    audit_path: Optional[str] = typer.Option(None, help="Path to a run audit JSON file."),
    status: Optional[str] = typer.Option(None, help="Comma-separated statuses to include, e.g. warn,fail."),
    format: str = typer.Option("jsonl", help="Output format: jsonl or json."),
) -> None:
    """Emit data quality events for developer and AI-agent debugging."""
    audit, _path = _resolve_audit_payload(run_id=run_id, audit_path=audit_path)
    events = quality_events_from_audit(audit)
    if status:
        allowed = {part.strip().lower() for part in status.split(",") if part.strip()}
        events = [event for event in events if str(event.get("status")).lower() in allowed]
    if format == "json":
        console.print_json(data=events)
        return
    if format != "jsonl":
        raise typer.BadParameter("format must be jsonl or json")
    for event in events:
        console.print(json.dumps(event, sort_keys=True, ensure_ascii=False))


@app.command("quality-open")
def quality_open(
    artifact_ref: str = typer.Option(..., help="Artifact ref such as tool_call:17."),
    run_id: Optional[str] = typer.Option(None, help="Run id to locate under eval_results."),
    audit_path: Optional[str] = typer.Option(None, help="Path to a run audit JSON file."),
    include_output: bool = typer.Option(True, help="Include the raw tool output in the JSON payload."),
) -> None:
    """Open a specific quality artifact from a run audit log."""
    audit, path = _resolve_audit_payload(run_id=run_id, audit_path=audit_path)
    artifact = open_artifact_from_audit(audit, artifact_ref)
    if not artifact:
        raise typer.BadParameter(f"Artifact not found: {artifact_ref}")
    artifact["audit_path"] = str(path)
    if not include_output:
        output = str(artifact.get("output") or "")
        artifact["output"] = f"<redacted:{len(output)}_chars>"
    console.print_json(data=artifact)


@app.command()
def analyze():
    run_analysis()


if __name__ == "__main__":
    app()

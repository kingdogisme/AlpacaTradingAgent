from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.integrations.robinhood_mcp import (
    RobinhoodMCPError,
    RobinhoodMCPClient,
    RobinhoodOAuthConfig,
    RobinhoodPKCEFlow,
    default_token_path,
    exchange_oauth_callback,
    load_json_file,
    mask_account_number,
    open_authorization_url,
    save_json_file,
    start_oauth_flow,
    summarize_token,
    wait_for_oauth_callback,
)


def _token_path(path: str | None = None) -> Path:
    return Path(path or DEFAULT_CONFIG.get("robinhood_mcp_token_path") or default_token_path()).expanduser()


def robinhood_login(
    callback_url: Optional[str] = typer.Option(None, help="Full OAuth callback URL returned by Robinhood."),
    token_path: Optional[str] = typer.Option(None, help="Where to store the Robinhood OAuth token JSON."),
    pending_path: Optional[str] = typer.Option(None, help="Where to store the pending PKCE login JSON."),
    redirect_uri: Optional[str] = typer.Option(None, help="OAuth redirect URI registered for this flow."),
    open_browser: bool = typer.Option(False, "--open-browser", help="Open the authorization URL in the default browser."),
    listen: bool = typer.Option(False, "--listen", help="Start a local callback listener and finish login automatically."),
    timeout_seconds: float = typer.Option(180.0, help="OAuth listener timeout in seconds."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    """Start or complete Robinhood MCP OAuth login."""
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    target = _token_path(token_path)
    pending = Path(pending_path or str(target.with_suffix(".pending.json"))).expanduser()
    if callback_url:
        flow = RobinhoodPKCEFlow.from_dict(load_json_file(pending))
        token = exchange_oauth_callback(callback_url, flow=flow)
        save_json_file(target, token)
        if pending.exists():
            pending.unlink()
        typer.echo(
            json.dumps(
                {
                    "status": "authenticated",
                    "token_path": str(target),
                    "token": summarize_token(token),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    config = RobinhoodOAuthConfig(
        mcp_url=str(DEFAULT_CONFIG.get("robinhood_mcp_url") or "https://agent.robinhood.com/mcp/trading"),
        redirect_uri=redirect_uri or str(DEFAULT_CONFIG.get("robinhood_mcp_redirect_uri") or "http://127.0.0.1:8765/oauth/callback"),
        client_name="AlpacaTradingAgent",
    )
    flow = start_oauth_flow(config)
    save_json_file(pending, flow.to_dict())
    if open_browser:
        open_authorization_url(flow.authorization_url)
    if listen:
        typer.echo(
            json.dumps(
                {
                    "status": "waiting_for_callback",
                    "authorization_url": flow.authorization_url,
                    "redirect_uri": flow.redirect_uri,
                    "pending_path": str(pending),
                    "token_path": str(target),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        callback = wait_for_oauth_callback(flow.redirect_uri, timeout_seconds=timeout_seconds)
        token = exchange_oauth_callback(callback, flow=flow)
        save_json_file(target, token)
        if pending.exists():
            pending.unlink()
        typer.echo(
            json.dumps(
                {
                    "status": "authenticated",
                    "token_path": str(target),
                    "token": summarize_token(token),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(
        json.dumps(
            {
                "status": "authorization_required",
                "authorization_url": flow.authorization_url,
                "state": flow.state,
                "pending_path": str(pending),
                "token_path": str(target),
                "next_command": f"python3 -m cli.main robinhood-login --callback-url '<returned URL>' --token-path '{target}'",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def robinhood_probe(
    ticker: str = typer.Option("NVDA", help="Ticker to quote."),
    token_path: Optional[str] = typer.Option(None, help="Robinhood OAuth token JSON path."),
    account_number: Optional[str] = typer.Option(None, help="Optional account_number for portfolio lookup."),
    format: str = typer.Option("json", help="Output format: json."),
) -> None:
    """Read a quote, accounts, and portfolio snapshots through Robinhood MCP."""
    if format != "json":
        raise typer.BadParameter("Only --format json is supported.")
    try:
        client = RobinhoodMCPClient(
            mcp_url=str(DEFAULT_CONFIG.get("robinhood_mcp_url") or "https://agent.robinhood.com/mcp/trading"),
            token_path=_token_path(token_path),
            timeout_seconds=float(DEFAULT_CONFIG.get("robinhood_mcp_timeout_seconds") or 20),
        )
        quote = client.get_equity_quote(ticker)
        accounts = client.get_accounts()
        selected_accounts = [
            account for account in accounts if not account_number or account.get("account_number") == account_number
        ]
        portfolios = []
        for account in selected_accounts:
            raw_number = account.get("account_number")
            if not raw_number:
                continue
            portfolios.append(
                {
                    "account_number": mask_account_number(str(raw_number)),
                    "portfolio": client.get_portfolio(str(raw_number)),
                }
            )
        typer.echo(
            json.dumps(
                {
                    "ticker": ticker.upper(),
                    "quote": quote,
                    "accounts": [_compact_account(account) for account in accounts],
                    "portfolios": portfolios,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except RobinhoodMCPError as exc:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                    "token_path": str(_token_path(token_path)),
                    "next_command": "python3 -m cli.main robinhood-login",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise typer.Exit(2) from exc


def _compact_account(account: dict) -> dict:
    return {
        "account_number": mask_account_number(str(account.get("account_number") or "")),
        "type": account.get("type"),
        "brokerage_account_type": account.get("brokerage_account_type"),
        "nickname": account.get("nickname"),
        "is_default": account.get("is_default"),
        "agentic_allowed": account.get("agentic_allowed"),
        "state": account.get("state"),
    }


__all__ = ["robinhood_login", "robinhood_probe"]

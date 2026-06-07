# Robinhood MCP Runbook

Robinhood's trading MCP endpoint is a streamable HTTP MCP server:
`https://agent.robinhood.com/mcp/trading`.

## Authentication Model

The MCP endpoint requires OAuth bearer tokens. The one-time OAuth `code` from
the callback URL is single-use by design; exchange it once for an access token
and refresh token, then store the token JSON locally. Future backend calls reuse
the access token and refresh it with the refresh token when needed.

Default local token cache:

```bash
~/.tradingagents/robinhood/oauth_token.json
```

## Login

Start the login flow:

```bash
python3 -m cli.main robinhood-login --listen --open-browser
```

This starts a local callback listener on the redirect URI, opens the
authorization page, and stores the token after Robinhood redirects back.

For a manual flow, run without `--listen`, open the returned
`authorization_url`, complete Robinhood authorization, then pass the full
callback URL back:

```bash
python3 -m cli.main robinhood-login
python3 -m cli.main robinhood-login \
  --callback-url 'http://127.0.0.1:8765/oauth/callback?code=...&state=...'
```

The command stores the token file with `0600` permissions and deletes the
pending PKCE file.

## Read-Only Probe

Verify quote, account discovery, and portfolio reads:

```bash
python3 -m cli.main robinhood-probe --ticker NVDA
```

This calls:

- `get_equity_quotes` for the quote
- `get_accounts` to discover account numbers
- `get_portfolio` for balances and buying power

## Environment

Add these values to `.env` when using Robinhood as the default ATA broker:

```bash
TRADINGAGENTS_BROKER_ADAPTER=robinhood
ROBINHOOD_MCP_URL=https://agent.robinhood.com/mcp/trading
ROBINHOOD_MCP_TOKEN_PATH=~/.tradingagents/robinhood/oauth_token.json
ROBINHOOD_MCP_REDIRECT_URI=http://127.0.0.1:8765/oauth/callback
ROBINHOOD_ACCOUNT_NUMBER=
ROBINHOOD_MCP_DRY_RUN=true
ROBINHOOD_MCP_LIVE_ORDERS_ENABLED=false
```

Alpaca and Robinhood are both broker execution adapters behind the same router.
The default route comes from `TRADINGAGENTS_BROKER_ADAPTER`, and explicit order
execution can override the broker per call:

```bash
python3 -m cli.main trade-plan-execute \
  --plan-id tp_xxx \
  --broker robinhood \
  --dry-run
```

Use `--submit-order` only after reviewing the broker payload and intentionally
allowing a real order submission. `--dry-run` is the default and keeps
Robinhood in review mode. Robinhood live submission is also blocked unless
`ROBINHOOD_MCP_LIVE_ORDERS_ENABLED=true`.

## Execution Flow

1. `ata-run` / `ata-report` + `ata-decide` creates a portfolio decision and
   conditional trade plan.
2. `trade-monitor --once` observes market data and moves triggered plans to
   `needs_review`.
3. A human or higher-level executor reviews the triggered plan.
4. `trade-plan-execute --broker robinhood --dry-run` reviews the order through
   Robinhood MCP and records a `broker_review` event without submitting.
5. `trade-plan-execute --broker robinhood --submit-order` submits only after
   explicit operator approval.

Robinhood account write tools require an `agentic_allowed=true` account. The
adapter refuses to choose non-agentic accounts for order review or placement.

## Adding More Brokers

Broker implementations should satisfy `BrokerAdapter` in
`tradingagents/execution/broker.py`, then be registered in
`create_broker_adapter`. Router-owned account and position methods are optional
but recommended so validation can use the same broker that will receive the
order.

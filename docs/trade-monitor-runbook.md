# Trade Monitor Runbook

This monitor watches active conditional trade plans and moves matched plans to
`needs_review`. Broker order review/submission is a separate explicit step via
`trade-plan-execute`.

## Required Infrastructure

- Persistent SQLite lifecycle DB: defaults to
  `~/.tradingagents/trade_lifecycle/trade_lifecycle.sqlite`.
- Alpaca market data credentials available to the running process.
- A process supervisor for long-running mode, for example systemd.
- Log retention for stdout/stderr from the monitor process.
- A health check that runs `trade-monitor-status` and alerts when heartbeat is
  stale.
- Optional review webhook endpoint for push alerts:
  `TRADINGAGENTS_TRADE_MONITOR_REVIEW_WEBHOOK_URL`.
- Optional OpenClaw IM target for push alerts:
  `TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_CHANNEL`,
  `TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_ACCOUNT`, and
  `TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_TARGET`.

## Runtime Behavior

- Default mode checks triggers only during regular US market hours. It uses
  Alpaca's market clock when credentials are available, then falls back to
  Monday-Friday, 09:30-16:00 ET.
- Each monitor pass writes a heartbeat to `trade_monitor_events`.
- Each triggered plan gets:
  - status `needs_review`
  - plan event `trigger_review_required`
  - optional webhook and/or OpenClaw IM notification if configured
- The next ATA/risk review should answer one of:
  `execute`, `resize`, `cancel`, or `supersede`.

## Commands

Run one pass:

```bash
python -m cli.main trade-monitor --once
```

Run continuously every 60 seconds:

```bash
python -m cli.main trade-monitor --interval-seconds 60
```

Smoke-test a supervised loop without leaving it running:

```bash
python -m cli.main trade-monitor --interval-seconds 1 --max-iterations 2 --no-lock
```

Check health and candidates:

```bash
python -m cli.main trade-monitor-status --stale-after-seconds 600
```

Run launch preflight:

```bash
python -m cli.main trade-monitor-preflight
```

Run outside regular hours for testing:

```bash
python -m cli.main trade-monitor --once --no-regular-hours-only
```

Review a triggered plan through a broker without submitting:

```bash
python -m cli.main trade-plan-execute --plan-id <plan_id> --broker robinhood --dry-run
```

Submit after explicit operator approval:

```bash
python -m cli.main trade-plan-execute --plan-id <plan_id> --broker robinhood --submit-order
```

OpenClaw Weixin notification example:

```bash
export TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_CHANNEL=openclaw-weixin
export TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_ACCOUNT=a6147788b220-im-bot
export TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_TARGET='o9cq806VliLSpongR9DiHYufYb2A@im.wechat'
```

## systemd Template

```ini
[Unit]
Description=TradingAgents trade monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/workspace/sde/AlpacaTradingAgent
EnvironmentFile=-/home/ubuntu/workspace/sde/AlpacaTradingAgent/.env
ExecStart=/home/ubuntu/workspace/sde/AlpacaTradingAgent/.venv/bin/python -m cli.main trade-monitor --interval-seconds 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

The checked-in unit file is
`deploy/systemd/tradingagents-trade-monitor.service`.

Install and start:

```bash
sudo install -m 0644 deploy/systemd/tradingagents-trade-monitor.service /etc/systemd/system/tradingagents-trade-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now tradingagents-trade-monitor.service
```

Health check example:

```bash
/home/ubuntu/workspace/sde/AlpacaTradingAgent/.venv/bin/python -m cli.main trade-monitor-status --stale-after-seconds 600
```

## Current Limitations

- Market-hours filtering falls back to weekday and regular-session ET time when
  Alpaca's clock is unavailable, so the fallback alone does not know holidays or
  early closes.
- Trigger observations currently use latest quote plus daily bars. Intraday
  volume confirmation is approximate until minute bars are added.
- Review webhook is generic JSON POST. OpenClaw IM notification uses
  `openclaw message send` and records the command result in
  `trade_monitor_events`.
- Robinhood MCP broker setup is documented in
  `docs/robinhood-mcp-runbook.md`. Keep `ROBINHOOD_MCP_DRY_RUN=true` until the
  order approval path is deliberately enabled.

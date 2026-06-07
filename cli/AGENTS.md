# CLI Boundary

This folder owns human- and agent-facing command entrypoints. CLI code should
translate command arguments into service calls and compact JSON/table output; it
should not own research, portfolio policy, execution, or evaluation logic.

## Public Contract

- Keep `from cli.main import app` working.
- Keep `MessageBuffer` and existing command callbacks import-compatible.
- Do not remove command names without compatibility wrappers and tests.
- Prefer new commands as thin wrappers around `tradingagents.*` services.

## ATA V2 Boundary

- `ata-report`: Research Layer entrypoint.
- `ata-decide`: Portfolio Decision Layer entrypoint.
- `trade-monitor` and `trade-plan-*`: Execution Layer entrypoints.
- `ata-run`: V2 report + portfolio decision by default; use `--legacy-graph`
  only for the pre-V2 monolithic path.
- `cron-run`: Alpha Discovery handoff into V2 report + portfolio decision by
  default; use `--legacy-graph` only for the pre-V2 monolithic ATA graph.

## Agent Guidance

- Start in `cli/main.py` for registered commands.
- Use `cli/commands/` for grouped command ownership.
- Keep output stable and grep-friendly for AI agents.

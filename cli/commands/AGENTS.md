# CLI Commands Boundary

This folder owns modular Typer command groups. Command modules should be thin:
parse options, call a service, render compact output, and return.

## Rules

- Do not import WebUI modules from here.
- Do not implement business logic here; call `tradingagents.*` services.
- Preserve command callback compatibility when moving logic out of
  `cli/legacy_main.py`.
- Add tests under `tests/unit/cli` for new or changed commands.

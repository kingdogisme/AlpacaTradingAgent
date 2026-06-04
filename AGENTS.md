# AI Agent Guide

This repo is an auditable multi-agent market research system. Default to compact indexes and contracts before opening raw run artifacts.

## Start Here

- CLI app: `python -m cli.main --help`
- Agent map: `python -m cli.main agent-map --format json`
- Core runtime graph: `tradingagents/graph/trading_graph.py`
- Agent tool registry: `tradingagents/agents/utils/agent_utils.py`
- Dataflow public API: `tradingagents.dataflows.interface`
- Eval ledger: `tradingagents/eval/ledger.py`
- Web UI entrypoint: `webui/app_dash.py`

## Debug Path

Use this order unless you explicitly need raw payloads:

1. `python -m cli.main run-index --run-id <run_id> --format json`
2. `python -m cli.main quality-index --run-id <run_id> --format json`
3. `python -m cli.main retrieval-pack --type risk_review --run-id <run_id> --format json`
4. `python -m cli.main quality-open --run-id <run_id> --artifact-ref <ref> --no-include-output`
5. Open raw audit JSON only for narrow excerpts.

## Source Boundaries

Treat these as local artifacts, not source context:

- `.venv/`, `env/`
- `eval_results*/`, `eval_results_quarantine/`
- `logs/`
- `tradingagents/dataflows/data_cache/`
- `__pycache__/`, `.pytest_cache/`
- `.env`, `.env.bak.*`

## Compatibility Rules

- Keep `from tradingagents.dataflows import interface` and `from tradingagents.dataflows.interface import <name>` working.
- Keep `from cli.main import app`, `MessageBuffer`, and existing command callbacks working.
- Do not remove command names without adding compatibility wrappers and tests.
- Prefer new small modules for ownership; keep old modules as re-export or compatibility shims.

## Useful Greps

```bash
rg -n "@app.command|agent-map|run-index|quality-index" cli tests
rg -n "quality_details|artifact_ref|trace_spans" tradingagents tests
rg -n "def get_.*|class Toolkit|timing_wrapper" tradingagents/agents tradingagents/dataflows
rg -n "EpisodeLedger|CREATE TABLE|list_run_index" tradingagents/eval tests/unit/eval
```

## Tests

```bash
python3 -m pytest tests/unit/dataflows
python3 -m pytest tests/unit/cli
python3 -m pytest tests/unit/eval
python3 -m pytest tests/unit/agents
python3 -m pytest tests/unit/webui tests/integration/mocked/test_webui_dash_smoke.py
python3 -m pytest tests/unit tests/integration/mocked
```

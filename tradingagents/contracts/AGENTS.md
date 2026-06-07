# Contracts Boundary

This folder owns ATA V2 typed handoff contracts between layers.

## Owned Contracts

- `research.py`: `ResearchRequest`, `ResearchReport`, evidence ledger types.
- `decision.py`: `PortfolioContext`, `InvestmentDecision`, policy gate types.
- `execution.py`: `ExecutionResult`.
- `eval.py`: layer-aware evaluation targets and records.

## Rules

- Contracts must be side-effect free.
- Do not import LLM clients, WebUI, CLI, or broker clients here.
- Prefer explicit `schema_version` fields for durable artifacts.
- Keep contracts small enough for AI agents to inspect quickly.
- Add compatibility adapters outside this folder when legacy state differs from
  V2 contracts.

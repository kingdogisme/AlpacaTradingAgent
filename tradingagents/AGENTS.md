# Core Package Boundary

`tradingagents` owns the application domain: research agents, dataflows,
portfolio decisioning, execution lifecycle, evaluation, prompts, and contracts.
It should be usable without the WebUI.

## ATA V2 Layering

```text
contracts -> research/agents/dataflows -> portfolio -> execution/trade_lifecycle -> eval
```

Current code still contains legacy graph coupling. New work should prefer small
layer services and typed contracts over expanding `TradingAgentsGraph`.

## Compatibility

- Keep `tradingagents.dataflows.interface` public imports working.
- Keep existing graph and eval entrypoints as compatibility wrappers.
- Side effects belong in execution/lifecycle services, not research contracts
  or analyst prompts.

## Agent Guidance

- Start with `contracts/` for V2 schemas.
- Use `docs/ata-v2-architecture.md` for target boundaries.
- Use raw audit artifacts only after checking indexes and retrieval packs.

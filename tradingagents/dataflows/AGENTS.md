# Dataflows Boundary

Dataflows own external and cached data access. They normalize source payloads
for analysts and deterministic services.

## Public Contract

- Keep `from tradingagents.dataflows import interface` working.
- Keep `from tradingagents.dataflows.interface import <name>` working.
- Prefer adding public functions through `dataflows/interface/` modules.

## ATA V2 Rules

- Alpaca market data is allowed as a data source.
- Alpaca broker/order side effects do not belong in research dataflows long
  term; use execution broker adapters for order placement.
- Preserve source freshness, point-in-time, and quality metadata where possible.

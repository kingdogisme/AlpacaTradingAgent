# Dataflows Unit Tests Boundary

Tests here cover data adapters, freshness, quality wrappers, and public
interface compatibility.

## Rules

- Mock provider clients and network calls.
- Verify point-in-time and stale/fallback metadata.
- Keep `tradingagents.dataflows.interface` compatibility covered.

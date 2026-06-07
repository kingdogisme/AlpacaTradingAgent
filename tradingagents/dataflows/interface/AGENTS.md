# Dataflows Interface Boundary

This folder owns the public data API surface for agents and services.

## Rules

- Keep imports stable and backward compatible.
- Prefer small grouped modules by source domain: market, technical, news,
  fundamentals, macro.
- Avoid exposing raw provider payloads unless explicitly needed.
- Include quality/freshness information in returned summaries when available.

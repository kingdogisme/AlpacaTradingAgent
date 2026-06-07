# Portfolio Unit Tests Boundary

Tests here cover deterministic portfolio policy, factor gates, risk overlays,
and V2 portfolio decision contracts.

## Rules

- Use mocked `PortfolioContext` data.
- Verify sizing math and gate behavior explicitly.
- Do not submit orders.

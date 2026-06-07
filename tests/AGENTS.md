# Tests Boundary

Tests own deterministic verification for units and mocked integrations.

## Rules

- Keep external-network tests under `tests/smoke` and gated.
- New V2 contracts need unit tests near the layer they protect.
- Prefer mocked service boundaries over live broker or web calls.
- Preserve compatibility tests for CLI and public imports.

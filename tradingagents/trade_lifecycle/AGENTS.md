# Trade Lifecycle Boundary

This folder owns Execution Layer state management: conditional plans, monitor
observations, pre-trade validation, lifecycle repository, and paper-only
execution handoff.

## Rules

- Consume approved/active plans; do not reinterpret research thesis.
- Keep live-account automatic execution forbidden.
- Keep broker side effects behind validator-approved paths.
- Record lifecycle events append-only where possible.
- Tests belong under `tests/unit/trade_lifecycle`.

# Smoke Tests Boundary

Smoke tests may touch real external services and must remain opt-in.

## Rules

- Require explicit environment gating such as `RUN_EXTERNAL_TESTS=1`.
- Never run as part of default unit/integration test suite.
- Do not mutate live trading accounts.

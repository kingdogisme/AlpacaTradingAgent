# Trade Lifecycle Unit Tests Boundary

Tests here cover Execution Layer models, repository, monitor, validator, and
paper-only execution paths.

## Rules

- Mock Alpaca broker helpers.
- Verify state transitions, reason codes, paper-only checks, and idempotency.
- Do not reinterpret research reports here.

# Unit Tests Boundary

Unit tests should be deterministic, local, and fast.

## Rules

- Do not require external API credentials.
- Patch broker/data providers at module boundaries.
- Add tests for contract validation, policy math, parsers, and command output.

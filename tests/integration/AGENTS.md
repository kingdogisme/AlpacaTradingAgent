# Integration Tests Boundary

Integration tests cover multi-module behavior with mocked external boundaries.

## Rules

- No real external APIs.
- Exercise service/graph flows through public entrypoints.
- Keep failures diagnosable by layer where possible.

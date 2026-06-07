# GitHub Workflows Boundary

This folder owns CI workflow definitions.

## Rules

- Run deterministic unit/mocked integration tests by default.
- Keep external smoke tests opt-in.
- Avoid workflow steps that mutate repository-tracked files.

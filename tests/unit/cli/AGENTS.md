# CLI Unit Tests Boundary

Tests here cover command registration, callback compatibility, and compact
output behavior.

## Rules

- Use Typer test runners where possible.
- Mock services rather than executing full agent runs.
- Preserve command names and import compatibility.

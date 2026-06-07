# Prompt Templates Boundary

Templates are grouped by agent role and shared context. They should be edited as
API-like contracts because downstream parsers and tests depend on them.

## Rules

- Keep final action tokens stable when compatibility requires them.
- Prefer structured sections over free-form prose for agent outputs.
- Mention Alpaca Intent only in portfolio/execution-related templates.
- Keep research templates free of account-position assumptions.

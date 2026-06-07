# WebUI Utilities Boundary

Utilities own UI state, storage, chart helpers, report recovery, and formatting
support.

## Rules

- Keep runtime UI state separate from durable audit/eval stores.
- Do not make WebUI state the source of truth for execution lifecycle.
- Prefer adapters that read core contracts and render UI-friendly summaries.

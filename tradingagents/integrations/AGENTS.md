# Integrations Boundary

This folder owns optional third-party integration adapters that are not the
stable public dataflow interface.

## Rules

- Keep provider-specific code isolated.
- Convert provider payloads into stable internal summaries before use by agents.
- Do not introduce broker side effects here unless behind an execution adapter.
- Document new API credentials and failure modes in config/docs.

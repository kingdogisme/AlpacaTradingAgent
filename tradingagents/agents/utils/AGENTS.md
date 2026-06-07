# Agent Utilities Boundary

This folder owns prompt-facing helpers: tool registry, structured invocation,
language handling, memory helpers, report context compression, source policy,
and tool quality wrappers.

## Rules

- Utilities should be reusable across agents and services.
- Do not add layer-specific side effects here.
- Keep `agent_utils.Toolkit` compatible with existing analysts.
- Prefer compact context builders over injecting raw artifacts.

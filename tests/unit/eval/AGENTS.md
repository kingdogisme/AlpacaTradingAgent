# Eval Unit Tests Boundary

Tests here cover EpisodeLedger, indexes, rewards, retrieval packs, quality
records, and layer-aware V2 eval contracts.

## Rules

- Use temporary SQLite paths.
- Do not depend on raw local eval_results artifacts.
- Keep deterministic reward/quality logic separate from LLM critic behavior.

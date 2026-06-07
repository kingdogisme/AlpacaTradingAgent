# Evaluation Boundary

Evaluation owns run indexes, episode ledger records, rewards, quality indexes,
retrieval packs, critic diagnostics, and future layer-aware scoring.

## ATA V2 Role

- Extend evaluation from final-action scoring to layer-aware evaluation:
  research, portfolio decision, execution, and outcome.
- Keep deterministic rewards separate from LLM critic interpretation.
- Store stable IDs and artifact refs; avoid duplicating large raw payloads.

## Rules

- Do not run production trading logic from eval modules.
- Use raw audit JSON as source of truth only after indexes are checked.
- Add tests under `tests/unit/eval` for schema/index changes.

# LLM Clients Boundary

This folder owns provider-agnostic LLM client creation and model discovery.

## Rules

- Keep provider differences behind `create_llm_client`.
- Do not put agent prompts or business policy here.
- Normalize model params consistently for quick/deep roles.
- Tests belong under `tests/unit/llm_clients`.

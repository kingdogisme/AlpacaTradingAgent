# LLM Clients Unit Tests Boundary

Tests here cover provider factories, model discovery, structured decisions, and
parameter normalization.

## Rules

- Do not call real model APIs.
- Keep provider-specific behavior behind factory contracts.

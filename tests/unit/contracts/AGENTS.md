# Contracts Unit Tests Boundary

Tests here cover ATA V2 layer contracts and side-effect-free validation.

## Rules

- Do not import broker, LLM, WebUI, or CLI runtime code unless testing import
  compatibility.
- Validate contract invariants and serialization behavior.

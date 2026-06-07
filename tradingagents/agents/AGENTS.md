# Agents Boundary

This folder owns LLM agent factories, schemas, and prompt-facing agent utilities.
Agents reason over evidence and produce structured text/objects; they should not
own persistence, broker execution, or CLI behavior.

## ATA V2 Role

- Analysts and researchers belong to the Research Layer.
- Trader/Risk Manager behavior should migrate behind the Portfolio Decision
  Layer.
- Direct Alpaca account reads from agents are legacy coupling and should be
  replaced with injected `PortfolioContext`.

## Rules

- Keep prompts aligned with schemas in `agents/schemas.py`.
- Use deterministic policy helpers for hard constraints.
- Do not submit orders or mutate trade lifecycle state from agent nodes.

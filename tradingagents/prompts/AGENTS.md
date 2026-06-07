# Prompts Boundary

This folder owns prompt loading and prompt templates.

## Rules

- Prompt templates should state role contracts and expected output shape.
- Keep layer terminology explicit: research report, portfolio decision,
  execution review.
- Do not encode broker authorization into research prompts.
- When changing prompt behavior, update related tests and evaluation metadata.

# Scripts Boundary

Scripts own operational helpers and scheduled-job glue.

## Rules

- Keep scripts thin wrappers around CLI or services.
- Do not implement core domain logic here.
- Scripts that can mutate external state must document safety assumptions.

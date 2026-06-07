# Alpha Discovery Scripts Boundary

This folder owns scheduling helpers for Alpha Discovery.

## Rules

- Invoke public CLI/services rather than duplicating discovery logic.
- Do not submit broker orders directly.
- Keep cron behavior auditable through Alpha Discovery events and ATA run IDs.

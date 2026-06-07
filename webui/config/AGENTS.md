# WebUI Config Boundary

This folder owns WebUI-specific constants and configuration helpers.

## Rules

- Do not duplicate core `tradingagents.default_config` semantics here.
- UI defaults should map cleanly to core config keys.
- Keep language and display config separate from execution policy.

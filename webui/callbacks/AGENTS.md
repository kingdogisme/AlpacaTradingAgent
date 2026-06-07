# WebUI Callbacks Boundary

Callbacks translate UI events into service calls and rendered component state.

## Rules

- Keep callbacks thin; domain logic belongs in `tradingagents`.
- Do not submit broker orders except through explicit execution/account actions.
- Keep callback IDs stable unless tests and layout are updated together.

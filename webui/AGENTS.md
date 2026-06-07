# WebUI Boundary

WebUI owns Dash presentation and callbacks for humans. It should call services
and render state; it should not own domain logic.

## ATA V2 UI Direction

- Separate Research Report, Portfolio Decision, and Execution Lifecycle views.
- Keep Alpaca account panels as execution/account views.
- Do not make account widgets part of research report generation.

## Rules

- Avoid importing CLI command code.
- Keep callbacks thin and testable.
- Preserve existing smoke tests when changing layout or callback IDs.

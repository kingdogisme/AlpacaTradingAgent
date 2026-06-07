# Manager Agents Boundary

Manager agents synthesize prior agent work into decisions. In V2, manager
responsibilities are split by layer.

## V2 Mapping

- `research_manager.py`: Research Layer synthesis into a thesis-quality report.
- `risk_manager.py`: legacy combined portfolio/risk judge. New work should move
  account-aware decisioning into Portfolio Decision Layer services and use
  injected `PortfolioContext`.

## Rules

- Do not add new broker calls here.
- Keep structured outputs parseable and schema-backed.
- Execution hard gates belong in `trade_lifecycle/validator.py` or execution
  services, not manager prompts.

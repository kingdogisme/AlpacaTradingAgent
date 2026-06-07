# Portfolio Boundary

This folder owns portfolio policy, sizing, risk budget, factor gates, and V2
Portfolio Decision Layer services.

## Current Contents

- `policy.py`: deterministic portfolio sizing/theme helpers.
- `decision_policy.py`: factor gates, risk overlays, and Alpaca intent
  classification support.

## ATA V2 Rules

- Portfolio decisioning may be account-aware through `PortfolioContext`.
- It may emit an `InvestmentDecision` and optional conditional plan draft.
- It must not submit broker orders.
- Hard execution gates remain in execution/trade lifecycle validators.

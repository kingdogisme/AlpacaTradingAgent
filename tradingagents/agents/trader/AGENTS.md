# Trader Agent Boundary

The trader agent is legacy portfolio-decision logic. In V2 it should become a
Portfolio Decision Layer component or adapter.

## Rules

- Convert research into proposed actionability, sizing, trigger, and
  invalidation.
- Use injected portfolio/account context rather than direct Alpaca reads.
- Do not persist trade plans or submit orders.
- Keep any conditional plan output structured; natural-language parsing is only
  a compatibility fallback.

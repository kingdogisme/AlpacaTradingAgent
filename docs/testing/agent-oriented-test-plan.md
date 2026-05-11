# Agent-Oriented Test Plan

## Summary

This plan defines deterministic contracts for each agent role and the graph that
orchestrates them. Tests should validate state shape, prompt inputs, tool
selection, executable action preservation, and side effects without calling
external services.

## Analyst Agents

- Market, Social, News, Fundamentals, and Macro analysts must select tools from
  config and capability checks: `online_tools`, credential availability, asset
  type, and trading horizon.
- Each analyst prompt must include ticker/date context, active tool names, and
  horizon instructions.
- Each analyst node must write its report field and return messages.
- If the first model response lacks `FINAL TRANSACTION PROPOSAL`, the node must
  request or append a final recommendation while preserving the analysis body.

## Research Agents

- Bull and Bear researchers must update `investment_debate_state` with role
  history, message lists, `current_response`, and incremented `count`.
- Research prompts must consume the cross-analyst context packet and compact
  debate digest.
- Round-limit behavior is owned by `ConditionalLogic` and must route to
  Research Manager at the configured boundary.

## Research Manager

- Structured output should be used when available and fall back to free text on
  unsupported models or runtime errors.
- Advisory ratings are metadata only. The executable action must come from
  `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**` or
  `**LONG/NEUTRAL/SHORT**`.
- The node must write `investment_plan` and mirror it into
  `investment_debate_state["judge_decision"]`.

## Trader

- Trader prompts must include current Alpaca position/account context via mocked
  `AlpacaUtils` helpers in deterministic tests.
- Trader output must preserve exactly one executable final action line for the
  selected mode.
- If the model omits the final line, the node must default to `HOLD` in
  investment mode or `NEUTRAL` in trading mode and append the required line.

## Risk Agents And Risk Manager

- Risky, Safe, and Neutral agents must update only their speaker-specific
  histories/messages plus shared risk history/count/latest speaker.
- Risk Manager must use structured fallback, preserve executable action, and
  write `final_trade_decision`, `recommended_action`, `trading_mode`,
  `trading_horizon`, and `current_position`.
- Crypto short execution remains prohibited in `AlpacaUtils.execute_trading_action`
  even when `allow_shorts=True`.

## Graph Orchestrator

- `Propagator` must initialize all analyst report fields, macro report,
  report context, and debate states.
- `GraphSetup` must route parallel analysts through `Build Report Context`
  before research agents; sequential mode must preserve selected analyst order.
- `TradingAgentsGraph.propagate` mocked runs must write full state logs, memory
  logs, audit summaries, and clear checkpoints after successful checkpointed
  runs.
- Failed runs must finish audit logging with `failed` status and an error
  summary.


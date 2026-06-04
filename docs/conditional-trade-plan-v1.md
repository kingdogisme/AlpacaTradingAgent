# Conditional Trade Plan v1

## Purpose

Conditional Trade Plan v1 turns AlpacaTradingAgent from a research-report
system into a controlled semi-automated trading decision system.

The core change is architectural: the final output is no longer only a
natural-language recommendation such as `BUY`, `HOLD`, or `SELL`. A completed
run also produces an approved, structured, monitorable trade plan. That plan
defines when a trade is allowed, when it is invalid, how much risk is allowed,
and what must be rechecked before an order is sent.

Current implementation status: the trade lifecycle package, SQLite repository,
monitor service, pre-trade validator, paper-only execution path, and structured
plan field are implemented. Real-time news blockers, full OMS/EMS order
reconciliation, and richer portfolio simulation remain v1.1 backlog items.

The v1 design intentionally separates four responsibilities:

- Signal generation: research/trader/risk agents produce and approve the plan.
- Monitoring: an independent service watches market conditions.
- Pre-trade validation: a lightweight validator decides whether a triggered
  plan may actually execute.
- Execution: existing Alpaca order helpers place paper-trading orders only
  after validation passes.

This avoids the current failure mode where each new analysis run can behave
like a fresh standalone opinion and potentially overwrite older intent.

## Target Architecture

```text
agent research run
  -> trader proposal
  -> risk-approved ConditionalTradePlan
  -> trade_lifecycle SQLite DB
  -> monitor service
  -> pre_trade_validator
  -> paper Alpaca order execution
  -> lifecycle event/audit rows
```

### Signal Generation

The agent stack remains responsible for research, debate, synthesis, and risk
approval. The approved output includes a structured plan in addition to the
existing final report text.

The canonical source is `conditional_trade_plan` in final state or a
`conditional_trade_plan_json:` line emitted by Risk Judge structured output.
Natural-language parsing is only a compatibility fallback and supports both
English and the default `zh-CN` labels. BUY/LONG/SELL/SHORT plans missing a
numeric trigger or numeric invalidation are stored as rejected/non-executable,
not activated.

The plan should include:

- symbol
- action or side
- entry or trigger policy
- invalidation condition
- risk budget
- maximum notional exposure
- valid-until timestamp
- source run ID
- status
- debounce or hysteresis policy

Research and trader agents may draft a plan, but v1 treats only the Risk Judge
output as the approved source of truth. Drafts should not become active plans
unless risk approval completes.

### Monitoring

The monitor is a separate service, not part of the LLM graph. It periodically
loads active plans, fetches current market data, evaluates trigger conditions,
and records observations.

The v1 monitor should watch:

- price relative to entry or trigger levels
- volume/liquidity proxies
- RSI and moving averages
- gap risk
- plan expiry

News and major event monitoring should be represented as structured event
payloads in v1, with SellTheNews or other live sources added behind config
flags. News should not be a hard dependency for the first monitor release.

### Pre-Trade Validation

The pre-trade validator runs only when a plan is triggered. It is intentionally
lighter than a full deep agent rerun.

The validator must check:

- plan status is active
- current time is before `valid_until`
- trigger condition is still true
- invalidation condition has not fired
- execution is paper-only
- position state still matches the plan assumption
- max notional and risk budget are not exceeded
- liquidity and gap risk are acceptable
- action is executable under current trading mode

The validator returns a structured validation result:

- approved or rejected
- reason code
- human-readable explanation
- market snapshot used for the decision
- execution policy if approved

### Execution

v1 automatic execution is limited to Alpaca paper trading. If the configured
Alpaca account is live, the validator must reject execution and record the
rejection event.

Existing Alpaca helper behavior should be reused after validation:

- `BUY` or `LONG` may open/add a long position.
- `SELL` may close an existing long position.
- `HOLD` or `NEUTRAL` must not place an order.
- Crypto shorting remains unsupported.

## Data Model

Use a dedicated trade lifecycle SQLite database rather than EpisodeLedger or
Alpha Discovery storage.

Default path:

```text
~/.tradingagents/trade_lifecycle/trade_lifecycle.sqlite
```

Config key:

```text
trade_lifecycle_db_path
```

### `trade_plans`

One row per approved trade plan.

Recommended fields:

- `plan_id`: stable unique ID
- `source_run_id`: originating agent run
- `symbol`
- `trading_mode`: investment or trading
- `horizon`: swing, position, or trend
- `action`: BUY/HOLD/SELL/LONG/NEUTRAL/SHORT
- `status`: draft, active, triggered, needs_reconciliation, executed, expired,
  rejected, cancelled, superseded
- `created_at`
- `updated_at`
- `valid_until`
- `entry_policy_json`
- `invalidation_policy_json`
- `risk_budget_json`
- `execution_policy_json`
- `monitoring_policy_json`
- `thesis`
- `raw_plan_json`

`valid_until` is mandatory. A plan without expiry is not monitorable and must
not become active.

### `trade_plan_events`

Append-only event log for lifecycle changes.

Recommended event types:

- `created`
- `activated`
- `monitor_observed`
- `triggered`
- `validation_passed`
- `validation_rejected`
- `order_submitted`
- `order_failed`
- `expired`
- `superseded`
- `cancelled`

Each event should include `event_time`, `plan_id`, `event_type`, `message`, and
`payload_json`.

### `trade_plan_validations`

Stores validator decisions independently from raw monitor events.

Recommended fields:

- `validation_id`
- `plan_id`
- `validated_at`
- `approved`
- `reason_code`
- `message`
- `market_snapshot_json`
- `risk_snapshot_json`
- `execution_policy_json`

Validation rows include stable `reason_code` values so tests, UI, and lifecycle
events do not depend on free-text reason wording.

## Plan Arbitration Rules

The system should not let each new analysis run casually overwrite an active
plan.

Apply the following priority order:

1. Hard risk controls win. Invalidation breach, stale signal, liquidity
   deterioration, live-account execution, and major negative risk events reject
   the plan.
2. Major new information wins. Earnings, financing, regulation, accidents,
   guidance changes, or equivalent material events may supersede an older plan.
3. No major new information means keep the existing plan. Do not overwrite just
   because the LLM phrased the thesis differently.
4. Every active plan must have `valid_until`; expired plans are stale and must
   be expired or rerun.
5. Conflicting repeated analysis windows should be reconciled conservatively:
   use the intersection of executable entry zones, the smaller risk budget, the
   nearer expiry, and the stricter invalidation.

Useful terminology:

- signal decay: signal strength declines with time
- stale signal: expired or outdated plan
- pre-trade risk check: final lightweight validation before execution
- trade lifecycle management: state tracking from plan creation to execution or
  cancellation
- signal arbitration: resolving conflicting agent runs
- hysteresis/debounce: avoiding repeated trigger/untrigger noise
- execution policy: deterministic order rules derived from the approved plan

## Monitor v1 Behavior

The monitor should support two CLI modes:

```bash
python -m cli.main trade-monitor --once
python -m cli.main trade-monitor --interval-seconds 60
```

`--once` performs a single scan and exits. Interval mode loops until stopped.

For each active plan:

1. Expire the plan if `valid_until` has passed.
2. Fetch current price/quote and lightweight technical data.
3. Record a `monitor_observed` event.
4. If trigger conditions are met for the required consecutive observations,
   mark or event the plan as triggered.
5. Run the pre-trade validator.
6. If validation fails, record rejection and leave the plan rejected or active
   depending on reason.
7. If validation passes and Alpaca is paper, submit the order through existing
   execution helpers with a deterministic idempotency/client order reference.
8. Record order result and update final plan status. If a process is interrupted
   after trigger and before order result, the plan should be left in
   `needs_reconciliation` or reconciled before another order is attempted.

The monitor must never directly place orders without the validator result.

## WebUI And Existing Execution Path

The current WebUI path can run analysis and optionally trade immediately after
analysis. With Conditional Trade Plan v1, that path should change:

- Analysis completion still shows `final_trade_decision`.
- The final state also includes `conditional_trade_plan`.
- If optional execution is enabled, the system activates the plan and evaluates
  whether it is immediately triggered.
- If immediately triggered, execution still goes through
  `PreTradeValidator`.
- If not triggered, the monitor owns future execution.

This preserves existing report UX while removing direct report-to-order
execution.

## Safety Defaults

v1 safety defaults are conservative:

- Live Alpaca execution is rejected.
- Paper execution is the only allowed automatic execution mode.
- HOLD and NEUTRAL never submit orders.
- Expired plans never execute.
- Plans missing `valid_until` never become active.
- Plans missing a valid trigger or invalidation should be stored as rejected or
  non-executable rather than guessed into an order.
- Flat investment-mode SELL and duplicate BUY while already LONG do not submit
  broker orders.
- Validator failure should be recorded as structured lifecycle data, not hidden
  in console logs only.

## Testing Requirements

Unit tests should cover:

- plan schema serialization and required `valid_until`
- status transitions
- repository schema creation
- upsert and active-plan listing
- event append and validation record append
- expiry handling
- validator rejection for expired plan, invalidation breach, live account,
  exceeded risk cap, liquidity risk, and gap risk
- validator approval producing a deterministic execution policy
- monitor `--once` triggering a mocked paper order

Integration tests should cover:

- mocked graph run writes an approved `conditional_trade_plan`
- existing `final_trade_decision` remains compatible
- WebUI/CLI execution cannot bypass validator

Safety tests should cover:

- `alpaca_use_paper=False` prevents order submission
- HOLD/NEUTRAL plans do not place orders
- expired plans are ignored by monitor execution

## Implementation Notes

The first implementation should prefer a narrow vertical slice over a broad
rewrite:

- Add a new `tradingagents.trade_lifecycle` package.
- Keep EpisodeLedger unchanged except for optional source-run references.
- Derive v1 plans from the final risk decision with deterministic parsing where
  possible.
- Preserve existing natural-language reports.
- Keep all broker execution behind validator approval.
- Record lifecycle state in SQLite even when execution is disabled or rejected.

This provides the minimum durable substrate for future work such as strategy
cards, model committees, signal reconciliation, and richer OMS/EMS integration.

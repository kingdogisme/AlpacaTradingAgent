# ATA V2 Architecture Refactor

## Purpose

ATA V2 evolves AlpacaTradingAgent from a single monolithic trading-agent graph
into a three-layer auditable decision system:

```text
Research Layer -> Portfolio Decision Layer -> Execution Layer
```

The current system already contains valuable production assets: analyst agents,
dataflows, tool-quality controls, run audit logs, EpisodeLedger, portfolio
policy helpers, and trade lifecycle infrastructure. V2 is therefore not a
rewrite of the feature set. It is a responsibility-boundary refactor.

The default V2 product is a **research report plus portfolio decision plus
optional conditional trade plan**. Execution remains a separate controlled
lifecycle.

## Current Architecture Assessment

Current main flow:

```text
Analysts
-> report context
-> bull/bear debate
-> research manager
-> trader
-> risk debate
-> risk judge
-> final_trade_decision
-> conditional_trade_plan persistence
-> trade monitor / validator / Alpaca paper execution
```

Largest coupling points:

- `final_trade_decision` acts as human report, investment decision, Alpaca
  intent, and plan source.
- Trader and Risk Manager directly read Alpaca account/position state.
- Portfolio sizing policy, LLM judgment, and execution hard gates are
  interleaved.
- The graph persists conditional plans as part of a research run.
- Evaluation mostly indexes final action/outcome, not per-layer failure mode.

The audit question V2 must make easy to answer:

```text
Is this output a research conclusion, a portfolio recommendation, or an
executable order instruction?
```

## Target Layers

### 1. Research Layer

Purpose: decide whether a thesis is evidence-supported.

Inputs:

- symbol
- trade date
- horizon
- selected analyst set
- source policy
- optional user thesis

Output: `ResearchReport`.

Responsibilities:

- Build analyst reports: market, news, social, fundamentals, macro.
- Normalize thesis into verifiable variables.
- Build evidence ledger and source-distance map.
- Identify counter-evidence and kill conditions.
- Check whether the thesis is priced in.
- Produce A/B/C/D-style conclusion and confidence.
- Produce candidate actionability notes, but not account-specific execution
  approval.

Must not:

- Read Alpaca account positions for thesis-quality decisions.
- Place or imply broker orders.
- Mutate trade lifecycle state by default.

### 2. Portfolio Decision Layer

Purpose: translate research into account-aware investment action.

Input:

```text
ResearchReport + PortfolioContext + PolicyConfig
```

Output: `InvestmentDecision`.

Responsibilities:

- Decide human action: BUY/HOLD/SELL or LONG/NEUTRAL/SHORT.
- Decide actionability: buy_now, conditional, watchlist, no_trade.
- Calculate risk budget and sizing.
- Apply portfolio/theme/single-name policy.
- Generate trigger, invalidation, valid_until, and conditional plan draft.
- Assign Alpaca Intent: NO_ORDER, CONDITIONAL_ORDER, IMMEDIATE_ORDER.
- Explain why a strong thesis may still be no-trade due to portfolio context.

Must not:

- Submit orders.
- Override execution hard gates.
- Treat Alpaca Intent as broker authorization.

### 3. Execution Layer

Purpose: safely manage plan lifecycle and broker interaction.

Input:

```text
ExecutableTradePlan + MarketObservation + AccountSnapshot
```

Output: `ExecutionResult`.

Responsibilities:

- Monitor active plans.
- Evaluate trigger and invalidation.
- Validate paper/live status.
- Check buying power, current position, max notional, expiry, liquidity, and
  gap risk.
- Require manual review where configured.
- Submit Alpaca paper orders only after validation.
- Record lifecycle events, order results, and reconciliation status.

Must not:

- Reinterpret thesis.
- Let LLM decide order side or size.
- Execute live-account orders automatically.

## Layer Interfaces

The canonical contract package is `tradingagents.contracts`.

### ResearchRequest

```python
ResearchRequest:
    schema_version: Literal["v2"]
    request_id: str
    symbol: str
    trade_date: str
    horizon: Literal["swing", "position", "trend"]
    thesis: str | None
    selected_analysts: list[str]
    source_policy: dict
    output_language: str
    config_ref: str | None
```

### ResearchReport

```python
ResearchReport:
    schema_version: Literal["v2"]
    report_id: str
    request_id: str
    symbol: str
    trade_date: str
    horizon: str
    thesis: str
    conclusion: Literal["A", "B", "C", "D"]
    confidence: Literal["high", "medium", "low"]
    variable_map: list[ResearchVariable]
    evidence_ledger: list[EvidenceItem]
    counter_evidence: list[str]
    pricing_check: PricingCheck
    kill_conditions: list[str]
    next_sources: list[str]
    markdown: str
    audit_refs: dict
```

### PortfolioContext

```python
PortfolioContext:
    schema_version: Literal["v2"]
    account_snapshot: dict
    current_positions: list[PositionSnapshot]
    current_symbol_position: Literal["LONG", "SHORT", "NEUTRAL"]
    theme_exposures: dict
    policy_config: dict
    active_plan_reviews: list[PlanLifecycleReview]
```

### InvestmentDecision

```python
InvestmentDecision:
    schema_version: Literal["v2"]
    decision_id: str
    report_id: str
    symbol: str
    human_action: str
    advisory_rating: str | None
    actionability: Literal["buy_now", "conditional", "watchlist", "no_trade"]
    confidence: str
    thesis_summary: str
    risk_budget: dict
    sizing: dict
    trigger: dict | None
    invalidation: dict | None
    valid_until: str | None
    alpaca_intent: Literal["NO_ORDER", "CONDITIONAL_ORDER", "IMMEDIATE_ORDER"]
    conditional_trade_plan: dict | None
    policy_gate_results: list[PolicyGateResult]
    rationale: str
    audit_refs: dict
```

### ExecutionResult

```python
ExecutionResult:
    schema_version: Literal["v2"]
    execution_id: str
    plan_id: str
    symbol: str
    status: Literal["waiting", "needs_review", "rejected", "executed", "expired"]
    validation_passed: bool
    reason_codes: list[str]
    observation: dict
    account_snapshot: dict
    order_request: dict | None
    broker_response: dict | None
    lifecycle_event_refs: list[str]
```

## LLM Role By Layer

Research Layer:

- LLM is the core reasoning engine.
- It decomposes thesis, synthesizes evidence, finds counter-thesis, and writes
  memo.
- Deterministic code verifies source freshness, source distance, and required
  report sections.

Portfolio Decision Layer:

- LLM is a constrained investment committee.
- Deterministic policy engine computes gates, caps, sizing formulas, and hard
  constraints.
- LLM explains tradeoffs and converts evidence into a portfolio decision, but
  cannot bypass hard policy results.

Execution Layer:

- LLM is not a decision maker.
- Execution is deterministic state machine plus validator.
- Optional LLM use is limited to review summaries, operator explanations, or
  postmortem classification.

Rule:

```text
LLM handles uncertainty. Code enforces invariants.
```

## Reuse / Rewrite Matrix

| Area | V2 Decision | Rationale |
|---|---|---|
| Analyst agents | Reuse with prompt/schema cleanup | Existing market/news/social/fundamentals/macro agents are valuable research workers. |
| Dataflows interface | Reuse | Public API compatibility is required and source wrappers are already broad. |
| Tool quality/freshness | Reuse and strengthen | Already supports quality events, stale/fallback flags, and point-in-time policy direction. |
| Report context builder | Reuse with stage-specific budgets | Good foundation for AI-agent-friendly context compression. |
| LLM client factory | Reuse | Provider/model abstraction is already separate from graph logic. |
| Prompt loader/structured invoke | Reuse | Useful across all three layers. |
| RunAuditLogger | Reuse | Keep raw trajectory audit as source of truth. |
| EpisodeLedger | Reuse and extend | Add layer-aware records instead of replacing ledger. |
| Portfolio policy helpers | Reuse but relocate conceptually | Keep deterministic sizing/gates, expose through Portfolio Decision Layer. |
| Trade lifecycle models/repository | Reuse | Already close to V2 execution layer. |
| Trade monitor / validator | Reuse with stricter boundary | Should consume approved plans only, not research state. |
| Alpaca market data | Reuse as data source | Research may use Alpaca bars/quotes as market data. |
| Alpaca order helpers | Wrap behind execution adapter | Broker side effects must be isolated. |
| WebUI account panel | Reuse as execution/account view | Should not be part of research report generation. |
| Alpha discovery | Reuse as upstream candidate source | It feeds research requests, not execution directly. |
| `TradingAgentsGraph` monolith | Rewrite incrementally | Split orchestration into research and decision services. |
| `AgentState` | Rewrite into contracts | Current state mixes all layer data. |
| Trader/Risk Manager direct Alpaca reads | Rewrite | Use injected `PortfolioContext`; no direct broker dependency in prompts. |
| `final_trade_decision` semantics | Rewrite | Replace with `ResearchReport`, `InvestmentDecision`, `ExecutionResult`. |
| Natural-language plan parsing | Demote to compatibility fallback | Structured plan should be canonical. |
| Evaluation | Rewrite around layers | Current final-action scoring cannot diagnose where failures occur. |

## Proposed Package Shape

Keep backward compatibility, but introduce clearer V2 facades:

```text
tradingagents/contracts/
  research.py
  decision.py
  execution.py
  eval.py

tradingagents/research/
  service.py
  graph.py
  report_builder.py

tradingagents/portfolio/
  service.py
  context.py
  policy.py
  decision_policy.py

tradingagents/execution/
  service.py
  broker.py
  alpaca_broker.py
  lifecycle.py
```

Existing packages remain:

- `tradingagents.dataflows.interface`
- `tradingagents.trade_lifecycle`
- `tradingagents.eval`
- `cli.main`
- `TradingAgentsGraph` compatibility wrapper

## CLI Semantics

Add V2-first commands:

```bash
python3 -m cli.main ata-report --ticker NVDA --trade-date 2026-06-06 --horizon position
python3 -m cli.main ata-decide --report-id <report_id>
python3 -m cli.main trade-monitor --once
```

Compatibility:

- `ata-run` remains available.
- In V2 default mode, `ata-run` behaves like `ata-report + ata-decide`, not
  broker execution.
- `trade-monitor` remains the execution entrypoint.
- Existing `trade-plan-*` commands remain execution/lifecycle commands.

## Evaluation V2

Current eval should be extended from final-result evaluation into stage
evaluation.

### Research Evaluation

Measures:

- claim support rate
- source-distance quality
- point-in-time safety
- evidence coverage by variable
- counter-evidence completeness
- pricing-check completeness
- hallucination / unsupported claim count
- memo structure compliance

Target records:

```text
research_report
research_claim
source_quality
pricing_check
```

### Portfolio Decision Evaluation

Measures:

- decision/report consistency
- actionability correctness
- sizing math correctness
- policy gate compliance
- trigger/invalidation completeness
- Alpaca Intent correctness
- separation of thesis quality from account suitability

Target records:

```text
investment_decision
conditional_plan_draft
policy_gate_result
```

### Execution Evaluation

Measures:

- trigger evaluation correctness
- invalidation handling
- expired plan handling
- paper-only enforcement
- buying power and position mismatch handling
- lifecycle transition correctness
- idempotency and order reconciliation

Target records:

```text
execution_validation
monitor_observation
broker_order_attempt
lifecycle_transition
```

### Outcome Evaluation

Keep delayed market outcome evaluation, but attach it to the correct target:

- `research_report`: did thesis direction work over horizon?
- `investment_decision`: was actionability/sizing justified?
- `conditional_plan`: did trigger/invalidation behave correctly?
- `executed_order`: did realized execution outcome match plan?

Outcome should not be the only grade. A good process can lose money, and a bad
process can make money.

## AI-Agent-Friendly Development Rules

ATA V2 is designed for agents as maintainers and operators.

Rules:

- Every layer has small typed inputs and outputs.
- Every output includes stable IDs and audit refs.
- Raw artifacts remain available but are not default context.
- Agents should inspect indexes before raw JSON.
- Prompt templates declare their contract and output schema.
- Evaluation identifies layer failures, not only final action failures.
- Memory retrieval is scoped by layer: research memory, decision memory,
  execution memory.
- Side effects are isolated behind execution services.

Recommended agent workflow:

```text
agent question
-> agent-map
-> run-index / quality-index
-> layer-specific retrieval pack
-> selected artifact excerpt
-> raw audit only if needed
```

## Migration Plan

### Phase 0: Contracts And Documentation

- Create V2 architecture doc.
- Define Pydantic contracts for research, decision, execution, and eval records.
- Add schema version fields to all new contracts.
- Decide default command semantics: report + decision, no execution.

### Phase 1: Research Facade

- Wrap current analyst/research-manager portion as `ResearchService`.
- Return `ResearchReport`.
- Keep old graph path as compatibility.
- Stop research output from persisting trade plans by default.

### Phase 2: Portfolio Decision Facade

- Move trader/risk-manager behavior behind `PortfolioDecisionService`.
- Replace direct Alpaca reads with injected `PortfolioContext`.
- Use deterministic policy helpers before LLM explanation.
- Emit `InvestmentDecision` and optional `ConditionalTradePlan`.

### Phase 3: Execution Facade

- Wrap trade lifecycle into `ExecutionService`.
- Introduce broker adapter interface.
- Keep Alpaca order code only behind execution adapter.
- Ensure monitor consumes active plans, not research final state.

### Phase 4: Evaluation Refactor

- Add layer-aware target records.
- Extend retrieval packs by stage.
- Keep existing final-action reward resolver.
- Add deterministic graders for contract compliance and policy violations.

### Phase 5: UI And CLI Split

- UI separates Research Report, Portfolio Decision, and Execution Lifecycle.
- CLI adds V2 commands while preserving old names.
- `agent-map` documents V2 boundaries and debug paths.

## Acceptance Criteria

- A default ATA V2 run produces report + decision + optional conditional plan,
  with no broker order attempt.
- Research can run without Alpaca account credentials if market data fallback is
  available.
- Portfolio decision can be tested with mocked `PortfolioContext`.
- Execution can be tested with mocked plan, observation, account snapshot, and
  broker adapter.
- Existing imports from `tradingagents.dataflows.interface` and `cli.main`
  continue to work.
- Trade lifecycle tests continue to pass.
- Eval can report whether a failure came from research, decision, or execution.

## Assumptions And Defaults

- Default V2 output is `ResearchReport + InvestmentDecision`.
- Conditional plans may be created, but execution is separate.
- Alpaca automatic execution remains paper-only.
- LLM is never the final authority for execution hard gates.
- Existing implementation is migrated incrementally, not replaced in one large
  rewrite.
- `trade_lifecycle` remains the foundation of Execution Layer.
- `EpisodeLedger` remains the foundation of evaluation, extended with
  layer-aware records.

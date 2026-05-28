# AlpacaTradingAgent Evolution Roadmap

## Current Stage Outcome

After the first evaluation-infrastructure phase, the system changes from a
mostly prompt-driven LangGraph executor into an auditable decision data
pipeline.

The immediate effect is not reinforcement learning yet. The effect is that each
run can now become an evaluation episode:

- The run has a durable episode record in SQLite.
- The final decision is parsed into structured action fields.
- The audit JSON remains the detailed trajectory artifact.
- Future market outcomes can be written back as reward records.
- Reports can aggregate hit rate, alpha, reward, pending outcomes, and action
  distribution by model, horizon, and symbol.

This gives the project the missing prerequisite for future learning: the system
can start answering "did this decision work?" before attempting to answer "how
should the agent change itself?"

## What This Enables

The first phase enables four concrete workflows.

The system is also moving toward an architecture where AI agents are first-class
readers of history, memory, and evaluation data. See
[Agent/LLM-Friendly Architecture](agent-llm-friendly-architecture.md) for the
information hierarchy, retrieval-pack design, and token-budget contracts that
should guide future history and memory work.

The next execution-safety milestone is documented in
[Conditional Trade Plan v1](conditional-trade-plan-v1.md). That design upgrades
natural-language final recommendations into risk-approved, monitorable trade
plans with a dedicated lifecycle database, monitor service, pre-trade
validation, and paper-only automatic execution.

### 1. Decision Quality Tracking

Every completed run can be evaluated after the holding period. For swing
horizon, the default holding period is 5 trading days. For position and trend
horizons, the defaults are 63 and 126 trading days.

The reward resolver compares the asset return against a benchmark when one is
available:

- Equities use SPY.
- BTC uses no benchmark.
- Other crypto assets use BTC-USD.

The output is a scalar reward plus interpretable components: raw return,
benchmark return, alpha, oracle label, classification reward, and PnL-style
reward.

### 2. Comparable Experiments

Runs can now be grouped by model, horizon, symbol, or leakage risk. This makes
basic A/B testing possible:

- memory on vs. memory off
- debate rounds 1 vs. 3 vs. 5
- macro enabled vs. disabled
- risk debate enabled vs. simplified final decision
- quick/deep model combinations
- swing vs. position vs. trend horizon

The important change is that these comparisons can be made against the same
reward schema instead of relying on manual reading of reports.

### 3. Trajectory-Level Analysis

The ledger stores the audit artifact path rather than duplicating prompt and
tool payloads. The detailed trajectory still lives in the existing run audit
JSON.

This allows later analysis of:

- which tools were called
- which agent produced which intermediate report
- how much prompt/tool/LLM cost each run used
- whether an incorrect final action came from bad input data, bad synthesis, or
  poor risk adjustment

This is the core data needed for future credit assignment.

### 4. Safer Backtest Groundwork

Historical collection defaults to `online_tools=False` and marks the episode as
low leakage risk. If live web/news data is explicitly allowed, the episode is
marked high leakage risk and should not be mixed with low-leakage backtests by
default.

This does not fully solve point-in-time data yet, but it prevents the most
obvious failure mode: evaluating a 2024 decision using 2026 web/news context.

## External Lessons To Adopt

Recent agent engineering practices from Anthropic, OpenAI, Google, Microsoft,
LangGraph, and related open-source memory systems point in the same direction:
do not start with "make the agent learn." Start with observable traces,
repeatable evals, governed memory writes, and delayed reward attribution.

### 1. Eval-First Agent Development

Anthropic's eval guidance and OpenAI's trace/eval tooling both emphasize that
agent quality should be measured at the trajectory and outcome level, not only
by inspecting final text.

Implications for this project:

- Treat each trading run as a task trial with inputs, trajectory, final answer,
  and delayed outcome.
- Keep deterministic reward resolvers separate from LLM judges.
- Add LLM critics only as diagnostic tools, not as the reward source of truth.
- Track failure categories across full trajectories: data error, reasoning
  error, tool error, synthesis error, and risk-control error.

This validates the Episode Ledger direction: the ledger is the minimum substrate
needed before any credible self-improvement loop.

### 2. Trace And Span Discipline

OpenAI trace grading and Microsoft Agent Lightning both point to the same
infrastructure pattern: record execution traces in a neutral format, then run
training, grading, and analytics outside the production agent path.

Implications for this project:

- Keep agent execution and evaluation/training decoupled.
- Store stable run IDs across audit logs, episode rows, decision rows, rewards,
  reflections, and future prompt/config variants.
- Treat tool calls, LLM calls, node transitions, final decisions, and rewards as
  joinable spans of one trajectory.
- Prefer offline scoring and backtesting jobs over in-path self-modification.

This prevents the production trading workflow from becoming entangled with
experimental learning code.

### 3. Memory Must Be Layered

Claude Code memory, OpenAI Agents SDK memory, Google ADK memory, Letta/MemGPT,
and LangGraph memory all separate short-term state from durable memory. The
useful pattern is not one giant vector store. It is a governed memory system
with different write rules per memory type.

Recommended memory layers:

- Session state: current run context, transient debate state, selected tools,
  and temporary assumptions.
- Episodic memory: resolved trading episodes, final decisions, rewards, and
  linked audit artifacts.
- Semantic memory: distilled lessons that are supported by multiple episodes or
  a high-confidence resolved outcome.
- Procedural memory: reusable decision procedures and strategy cards.
- Asset memory: ticker/horizon-specific behavior summaries.
- Memory index: a compact human-readable map of durable memory files and stores,
  similar in spirit to a `MEMORY.md` index.

The key rule: raw reflections are not trusted memory. They are candidates. A
lesson should be promoted only when tied to evidence and versioned reward data.

### 4. Memory Retrieval Needs Its Own Policy

OpenAI's memory examples show that retrieval is not always the right primitive.
For persistent user or environment state, structured state can outperform
semantic search. For historical lessons, retrieval is useful only when scoped
by task, horizon, asset, market regime, and evidence quality.

Implications for this project:

- Do not inject every remembered lesson into every trading prompt.
- Retrieve by symbol, asset class, horizon, regime, and decision stage.
- Track which memories were retrieved into each episode.
- Evaluate memory-on vs. memory-off and memory-policy variants.
- Add negative memory signals: lessons that were retrieved but correlated with
  worse outcomes should be demoted.

Memory should become a measurable decision input, not a growing prompt appendix.

### 5. Critic Agents Should Diagnose, Not Grade

Anthropic's evaluator-optimizer pattern is useful, but in trading it should be
constrained. The critic can explain why a decision failed, but market outcome
and benchmark-adjusted reward must remain deterministic.

Implications for this project:

- Use deterministic reward records as the grading source.
- Use critic agents to produce structured failure tags and improvement
  candidates.
- Require critic outputs to cite episode IDs, reward components, and trajectory
  evidence.
- Store critic reflections separately from promoted memory.

This keeps LLM interpretation useful without letting it redefine success after
the fact.

### 6. Learning Should Start Outside The LLM

Agent Lightning, FinRL-style pipelines, and mature eval systems suggest that
the practical first learning layer should be a small policy or ranking layer
around the LLM agents, not direct RL over a frontier model.

Good first policy targets:

- which analysts to run
- debate depth
- memory retrieval policy
- prompt/config variant
- risk posture
- final action override
- position-size bucket

The LLM can remain the reasoning engine while the learned layer optimizes
selection, routing, and calibration from episode features and rewards.

## Remaining Limitations

This stage does not make the system self-learning.

The agent still does not:

- update LLM weights
- automatically mutate prompts
- automatically change agent routing
- promote or demote strategies
- learn a position-sizing policy
- perform portfolio-level simulation

The reward is currently direction-oriented and fixed-horizon. It is a clean
first metric, not a complete trading objective. It does not yet model portfolio
constraints, execution price, slippage, exposure limits, correlation, or
multi-position risk.

The system should therefore be described as:

> LLM workflow executor + auditable episode ledger + delayed reward store.

Not yet:

> Self-improving RL trading agent.

## Evolution Path

### Phase 2: Memory V2

Goal: make historical experience useful and governed by outcomes.

Recommended additions:

- Session memory: preserve current run state without writing it to durable
  memory by default.
- Episodic memory: store complete decision episodes and resolved outcomes using
  the Episode Ledger as the canonical source.
- Semantic memory: distill repeated lessons from successful and failed episodes.
- Procedural memory: store reusable decision procedures, not just textual
  advice.
- Asset profile memory: maintain ticker/horizon-specific behavior summaries.
- Memory index: add a compact `MEMORY.md`-style map that points agents and
  developers to durable memory stores, strategy cards, and lesson files.
- Memory governance: only promote lessons when they are backed by resolved
  rewards or repeated evidence.
- Memory retrieval policy: record which memories were retrieved for each
  episode, then evaluate retrieval policies like any other decision component.

This phase should replace "remember whatever the LLM reflected on" with
"remember outcome-backed lessons."

### Phase 3: Critic And Reflection Pipeline

Goal: turn rewards into actionable self-critique.

Recommended additions:

- A deterministic reward evaluator remains the source of truth.
- A critic agent reads the episode, trajectory, and reward components.
- The critic diagnoses failures but does not assign the reward.
- The critic produces failure tags such as:
  - bad timing
  - ignored macro risk
  - overweighted sentiment
  - weak stop/invalidation
  - missed benchmark regime
  - risk manager overrode correct trader signal
- Reflections are stored separately from raw decisions.
- Reflections include evidence links back to episode IDs.
- Reflections have lifecycle states: candidate, validated, promoted, demoted,
  archived.
- Promoted reflections become memory only after evidence thresholds are met.

This is the Reflexion-style step: no model training yet, but future prompts can
retrieve outcome-backed lessons.

### Phase 4: Experiment Registry And Promotion

Goal: make architecture and prompt changes measurable.

Recommended additions:

- Version all prompts, model settings, selected agents, and reward functions.
- Version memory retrieval policies and critic prompts.
- Define benchmark suites by symbol/date/horizon.
- Add champion/challenger reports.
- Add trace-level evals that score tool use, data leakage risk, decision
  consistency, and final-action calibration.
- Promote a prompt/config only if it beats the baseline on resolved reward and
  drawdown-aware metrics.
- Keep high-leakage and low-leakage experiments separate.

This prevents "self-evolution" from becoming random prompt churn.

### Phase 5: Strategy Library

Goal: store reusable, testable strategy procedures.

Recommended additions:

- Strategy cards with entry context, invalidation, horizon, required evidence,
  risk budget, and known failure modes.
- Link each strategy card to the episodes that support or refute it.
- Let agents retrieve candidate strategy cards before generating a final plan.
- Track strategy-level reward, not just action-level reward.
- Track when a strategy card was retrieved but not used.
- Demote strategy cards that underperform after sufficient resolved episodes.

This mirrors the useful part of Voyager-style lifelong learning: a skill library
that is selected and improved by evidence.

### Phase 6: Policy Layer And Offline RL

Goal: introduce learning without trying to train the whole LLM.

Recommended additions:

- Treat LLM agents as feature generators.
- Train a small decision or ranking layer over structured episode features.
- Start with supervised learning or contextual bandits.
- Later evaluate offline RL using the same episode/action/reward schema.

Candidate learned decisions:

- agent subset selection
- debate depth
- risk posture
- memory retrieval strategy
- prompt variant
- final action override
- position-size bucket

This is safer and more realistic than attempting direct RL on a closed-source
LLM.

For an implementation-ready backlog that expands the most valuable next steps
into concrete data contracts, tests, acceptance criteria, and agent-readable
debug surfaces, see
[Future Improvement Roadmap](future-improvement-roadmap.md).

## Near-Term Infrastructure Backlog

The next implementation stage should stay infrastructure-focused. The most
useful additions are:

1. Add memory reference tables: `memory_items`, `memory_links`,
   `memory_retrievals`, and `memory_promotions`.
2. Add a `CriticRecordV1` schema with episode ID, failure tags, evidence spans,
   improvement candidates, and lifecycle state.
3. Add trace normalization that converts audit JSON into span rows for prompts,
   LLM calls, tool calls, agent outputs, graph transitions, and final decisions.
4. Add experiment metadata for prompt version, model version, config hash,
   memory policy, critic version, and reward version.
5. Add benchmark suites with fixed symbol/date/horizon sets and leakage policy.
6. Add export to JSONL/Parquet for offline modeling and future RL/bandit work.
7. Add memory ablation reports: no memory, episodic only, semantic only,
   procedural only, and full memory.
8. Add critic ablation reports: no critic, critic-only diagnostics,
   critic-derived memory candidates, and promoted memory.

## Recommended Engineering Priorities

1. Keep the episode ledger stable and backwards compatible.
2. Add export tooling to JSONL/Parquet before training work starts.
3. Add deterministic benchmark datasets with low leakage risk.
4. Improve reward with max drawdown, volatility, and transaction-cost
   components.
5. Build memory promotion rules before increasing memory volume.
6. Add critic/reflection only after enough resolved episodes exist.

## Operational Commands

Collect historical episodes:

```bash
python -m tradingagents.eval collect \
  --symbols AAPL,MSFT \
  --dates 2026-01-02,2026-01-03 \
  --config config.json
```

Resolve rewards:

```bash
python -m tradingagents.eval score --as-of 2026-05-10
```

Generate reports:

```bash
python -m tradingagents.eval report \
  --since 2026-01-01 \
  --group-by model,horizon,symbol
```

Include high-leakage live-web episodes only when deliberately inspecting them:

```bash
python -m tradingagents.eval report --include-high-leakage
```

## Success Criteria For The Foundation

The foundation is healthy when:

- every successful run has one completed episode;
- every final decision has a parsed action;
- every mature episode has one reward record;
- reports can compare model/horizon/symbol groups;
- high-leakage and low-leakage episodes are separable;
- ledger failures never break trading analysis;
- future memory and RL work can consume the same episode/reward records.

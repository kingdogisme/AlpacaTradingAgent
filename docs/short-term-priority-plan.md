# Short-Term Priority Plan

## Summary

This plan ranks the most valuable near-term work outside the currently active
trade-lifecycle module.

The project has already moved beyond a pure report generator. The repo now has
substantial foundations for episode ledgers, run indexes, quality indexes,
retrieval packs, Memory V2, benchmark comparison, critic records, Alpha
Discovery, and portfolio/risk policy. The main short-term gap is not lack of
ideas; it is that several pieces exist but are not yet packaged into a tight
daily workflow with clear quality gates and agent-readable entrypoints.

The best short-term strategy is therefore:

1. Make completed runs easy to inspect through indexes and retrieval packs.
2. Make data-quality failures visible before they influence decisions.
3. Make memory useful only when it is outcome-backed and auditable.
4. Make prompt/model changes measurable through fixed benchmark suites.

Do not prioritize new trading execution features in this plan; those are
covered separately by Conditional Trade Plan v1.

## Current Completion Snapshot

### Mostly Built

- Episode Ledger: durable run records, decisions, rewards, trace spans,
  experiments, quality tables, memory tables, retrieval packs.
- Run/Quality Index: `build_run_index`, `build_quality_index`, CLI commands
  under `cli.main`.
- Retrieval Packs: `risk_review`, `ticker_horizon`, and `prompt_audit` pack
  builders.
- Reward Resolver: fixed-horizon reward and benchmark-adjusted alpha.
- Critic v1: deterministic failure tags and memory-candidate generation.
- Memory V2 basics: candidates, promotion/demotion, retrieval audit, simple
  ablation reporting.
- Data Quality V2 basics: observations, cross-source reconciliation, source
  reliability.
- Benchmark comparison: fixed suite loader and existing-run comparison.
- Portfolio/risk policy: horizon factor gates, sizing, crowding, momentum-crash
  overlays, theme concentration policy.
- Alpha Discovery: candidate repository, cron commands, confirmation, handoff,
  outcomes, health/events reporting.

### Main Gaps

- The run-index/retrieval-pack workflow is not yet the default debugging path.
- Quality reconciliation is available but not consistently run after every
  completed episode.
- Memory V2 is present but not fully connected into agent prompts as a governed
  retrieval input.
- Benchmark suites exist as capability, but the repo still needs curated suite
  files and a standard regression command.
- Critic output can create memory candidates, but critic runs are not yet a
  normal post-reward pipeline.
- Portfolio/risk simulation is still mostly policy and prompt context, not
  portfolio-level what-if simulation or exposure replay.

## Highest-Value Short-Term Work

### 1. Make Indexes The Default Debugging Surface

Goal: after every completed run, a developer or agent should inspect the run
through `run-index`, `quality-index`, and `retrieval-pack` before opening raw
audit JSON.

Recommended work:

- Add a post-run helper that builds `RUN_INDEX`, `QUALITY_INDEX`, and a
  `risk_review` retrieval pack automatically.
- Add a compact CLI command such as `run-summary --run-id <id>` that returns
  final action, confidence, quality status, critical failures, audit path, and
  recommended next debug commands.
- Update docs and README workflow examples to point agents to index commands
  first.
- Add tests proving raw long tool outputs are not included in default index JSON.

Why this is first: it immediately reduces debugging cost and makes every later
roadmap item easier to validate.

### 2. Promote Quality Reconciliation Into The Run Pipeline

Goal: data-quality warnings should be structured and visible without manual
commands.

Recommended work:

- Run quality reconciliation after `build_quality_index` for completed runs.
- Store cross-source mismatch, stale-source, missing-secondary-source, SEC
  precedence, news timestamp, and macro-recency checks as first-class rows.
- Include reconciliation summary in `run-index` flags or retrieval-pack summary.
- Add a fail-soft behavior: missing optional source records `unknown`, not a
  crash.

Why this is second: bad data is one of the fastest ways for a multi-agent
trading system to look smart while making poor decisions.

### 3. Wire Memory V2 Into Agent Retrieval Conservatively

Goal: memory should become a measurable input, not a growing prompt appendix.

Recommended work:

- Start with one controlled injection point: Risk Manager only.
- Default policy should retrieve only promoted ticker/horizon memories.
- Log every retrieved memory with run ID, stage, policy, rank, score, and
  source ref.
- Keep candidates queryable but mark them untrusted unless explicitly enabled.
- Add a config flag for `memory_policy=ticker_horizon_promoted_v1`.

Why this is third: the storage and retrieval primitives exist, but until memory
is used in a controlled stage, it cannot improve future runs or be ablated.

### 4. Add Curated Benchmark Suites And A Standard Regression Command

Goal: prompt/model/config changes should be compared against fixed cases before
becoming defaults.

Recommended work:

- Add small checked-in benchmark suite files under `docs` or a dedicated
  `benchmarks/` directory.
- Start with 10-20 cases across swing, position, trend, large-cap tech,
  semiconductors, crypto, and at least one non-US suffix.
- Add a single documented command for baseline-vs-candidate comparison using
  existing indexed runs.
- Require comparison output to include action changes, confidence changes,
  quality-status changes, missing cases, and reward deltas when resolved.

Why this is fourth: the comparison code exists, but without curated suites,
prompt changes remain hard to judge.

### 5. Close The Critic-To-Memory Loop

Goal: resolved rewards should automatically produce diagnostic records and
candidate memories.

Recommended work:

- Add a post-reward command or helper that runs the deterministic critic for
  newly resolved episodes.
- Create memory candidates from critic records.
- Keep promotion manual or reward-gated; do not auto-promote v1 memories.
- Add a report showing top failure tags by horizon, symbol, model, and prompt
  version.

Why this is fifth: it turns outcome resolution into actionable learning input
without pretending the system is self-learning.

## What To Defer

- Portfolio-level simulation engine: valuable, but it needs cleaner historical
  position/exposure data first.
- Learned routing or policy optimization: premature until benchmarks and memory
  ablation are routine.
- Full LLM critic pipeline: useful later, but deterministic critic records are
  enough for the next iteration.
- Strategy card marketplace or complex procedural memory: wait until promoted
  memories and benchmark suites are stable.
- More UI surfaces: CLI/JSON contracts should stabilize before larger UI work.

## Suggested Execution Order

1. Auto-build indexes and risk-review retrieval pack after completed runs.
2. Add `run-summary` CLI and document the default debug workflow.
3. Run quality reconciliation automatically and surface summary flags.
4. Inject promoted Memory V2 into Risk Manager behind a config flag.
5. Add curated benchmark suites and a standard comparison command.
6. Add critic-after-reward and memory-candidate generation workflow.

This order keeps every step useful on its own and avoids adding new reasoning
features before the observability path is stable.

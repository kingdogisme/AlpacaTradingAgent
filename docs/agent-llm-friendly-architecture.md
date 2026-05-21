# Agent/LLM-Friendly Architecture

## Purpose

AlpacaTradingAgent is increasingly built for AI agents as active system users,
not only for humans reading reports or code. This changes the architecture
target: historical runs, prompts, decisions, rewards, and memory should be easy
for an LLM agent to locate, summarize, compare, and cite without loading large
raw artifacts into context.

The goal is not to store less information. The goal is to separate raw
artifacts from compact indexes and task-specific summaries so agents can answer
questions such as:

- Why did similar `position` runs become HOLD?
- Which prompt version changed BUY/HOLD behavior?
- What evidence made a risk manager override a trader plan?
- Which historical episodes are most relevant to this ticker, horizon, and
  market regime?
- What should be retrieved for a new run, and what should stay out of the
  prompt?

## Core Principle

Design the system as an information hierarchy:

```text
human/agent question
-> compact directory/index
-> structured episode summary
-> selected spans or report excerpts
-> raw audit artifact only when needed
```

Agents should almost never start from raw run JSON, full markdown reports, or a
large vector search over everything. They should start from small, stable,
typed indexes that point to deeper artifacts.

## Source Freshness And Point-In-Time Safety

ATA supports both live analysis and historical analysis through `trade_date`.
Every source integration must preserve that distinction:

- Live analysis may use current SellTheNews, OpenAI web search, Alpha Vantage,
  live Finnhub snapshots, DeFiLlama, and options-positioning tools.
- Historical analysis must be point-in-time safe. If `trade_date` is before the
  current date, live-only sources are disabled by default.
- Official filing sources such as SEC EDGAR must filter filings and facts to
  records available on or before `trade_date`; latest filings must not leak into
  historical runs.
- Freshness gates should prefer `missing` over stale values. If a metric is not
  current enough for the analysis date, the report should state that it is
  missing/stale instead of showing an old value as usable evidence.
- Source policy should be explicit and configurable. The default
  `point_in_time_source_policy=auto` treats historical dates as point-in-time
  mode, while `live` and `historical` are available for controlled tests or
  operator overrides.

This rule is intentionally conservative. A historical run that lacks a source is
more useful than a historical run that unknowingly includes future information.

### OpenAI Source Fallback Policy

OpenAI web-search tools are intentionally treated as slow fallback sources, not
default data feeds. Each analyst should follow the same policy:

- `openai_sources_policy=fallback`: bind OpenAI source tools only when the
  faster non-OpenAI source family for that analyst is unavailable.
- `openai_sources_policy=eager`: bind OpenAI source tools even when faster
  sources are available. Use this for explicit experiments, not daily cron.
- `openai_sources_policy=disabled`: never bind OpenAI source tools.

The fast-source families are analyst-specific:

- fundamentals: SEC EDGAR, Alpha Vantage, Finnhub, SimFin, DeFiLlama
- news: SellTheNews, Finnhub, CoinDesk/CryptoCompare
- social: SellTheNews WSB/DD
- macro: FRED and SellTheNews macro

When OpenAI is skipped, the runtime should emit a compact reason that an LLM or
operator can grep without loading full logs:

```text
openai_source_skipped role=fundamentals reason=non_openai_sources_available policy=fallback
```

Longer term, the same event should be written into the run audit JSON. The
console log is the minimum implementation for local debugging and cron rollout.

## Why This Matters

Current audit logs are useful but expensive for LLMs to inspect. A single E2E
run can include long prompts, tool payloads, reports, debates, and final
decisions. Loading several runs directly causes three problems:

- Token waste: most raw text is irrelevant to the question being asked.
- Search friction: the agent must infer where decisions, configs, and evidence
  live instead of reading a stable map.
- Poor comparison: raw reports make it hard to compare action distributions,
  prompt versions, model settings, and outcome-backed lessons.

An LLM-friendly architecture treats every durable artifact as part of a
navigable knowledge system. The system should support progressive disclosure:
small summaries first, detailed evidence second, raw artifacts last.

## Artifact Layers

### 1. Raw Artifacts

Raw artifacts remain the source of truth for full auditability.

Examples:

- run audit JSON under `eval_results/<symbol>/TradingAgentsStrategy_logs/runs/`
- full analyst reports
- tool outputs
- prompts and model responses
- final report markdown

Rules:

- Keep raw artifacts durable and immutable when possible.
- Do not optimize raw artifacts for prompt size.
- Always link raw artifacts through stable run IDs.

### 2. Canonical Structured Records

Structured records are the queryable backbone.

Examples:

- `episodes`: run ID, symbol, date, horizon, selected analysts, config hash,
  status, final signal, audit path
- `decisions`: action, advisory rating, confidence, thesis, invalidation,
  risk budget, Alpaca action plan
- `trace_spans`: typed references to prompt, LLM call, tool call, agent output,
  graph transition, and final decision spans
- `experiments`: prompt version, model version, config hash, memory policy,
  critic version, reward version
- `rewards`: fixed-horizon returns, benchmark alpha, drawdown and cost fields
  as they become available

Rules:

- Prefer structured fields over text parsing.
- Keep records small enough to query in bulk.
- Store pointers to long payloads instead of duplicating them everywhere.

### 3. Agent-Readable Indexes

Indexes are compact maps designed for agents and developers.

Recommended indexes:

- `RUN_INDEX`: one row per run with symbol, date, horizon, action, confidence,
  prompt version, model pair, analyst set, status, and audit path.
- `PROMPT_INDEX`: role, template path, prompt version, behavioral contract, and
  known related tests.
- `MEMORY_INDEX`: memory stores, strategy cards, promoted lessons, rejected
  lessons, and retrieval policy names.
- `STRATEGY_INDEX`: strategy card IDs, horizon, required evidence, historical
  support/refutation, and active lifecycle state.
- `BENCHMARK_INDEX`: fixed symbol/date/horizon suites for prompt and model
  regression checks.

Rules:

- Each index should be readable without opening raw artifacts.
- Each row should include stable IDs for deeper lookup.
- Indexes should support both CLI queries and LLM agent browsing.

### 4. Task-Specific Summaries

Summaries are generated for recurring investigation tasks.

Examples:

- action-distribution summary by horizon and symbol
- HOLD-reason taxonomy for recent runs
- BUY-confirmation checklist failures
- risk-manager override summary
- prompt-version comparison summary
- ticker/horizon profile summary

Rules:

- Summaries should cite run IDs and evidence spans.
- Summaries are not source of truth; they are cached views.
- Stale summaries must include generation time and source filters.

### Official Structured Data Summaries

Official structured sources should be converted into compact, typed summaries
before reaching analyst prompts. SEC EDGAR is the reference pattern:

- cache raw `submissions` and `companyfacts` JSON under a source-specific cache
  path with TTLs
- expose a short Markdown report with CIK, latest filing references, metric
  trends, missing fields, stale filing warnings, and source tags
- keep raw JSON out of prompts unless an explicit debugging task asks for it
- record source URLs/accession numbers so an agent can reopen the exact filing
  reference when needed

This keeps fundamentals auditable without turning every ATA run into a large
raw-XBRL parsing task.

### 5. Retrieval Packs

Retrieval packs are compact context bundles injected into agents.

Examples:

- `ticker_position_pack`: recent resolved episodes for the same ticker and
  horizon, promoted asset lessons, active strategy cards, and risk constraints.
- `prompt_audit_pack`: prompt templates, related tests, historical action
  distribution, and known regressions.
- `risk_review_pack`: trader proposal, selected evidence claims, current
  portfolio constraints, and historical risk overrides.

Rules:

- Retrieval packs should have explicit token budgets.
- Packs should be built by policy, not by broad semantic search alone.
- Every retrieved item should be logged into the episode for later evaluation.

## Token Budget Contracts

Every agent-facing retrieval path should declare a budget and priority order.

Recommended default budgets:

```text
Run index scan:        1k-2k tokens
Episode summaries:    2k-4k tokens
Evidence spans:       2k-6k tokens
Prompt/template refs: 1k-3k tokens
Raw artifact excerpts: only on demand
```

Recommended priority order:

1. current task instruction
2. current run state
3. relevant structured records
4. promoted memory or strategy cards
5. selected evidence spans
6. raw artifact excerpts

Agents should not receive raw full history by default. Retrieval should be
scoped by symbol, horizon, date range, prompt version, model version, and
question type.

## Query Patterns To Support

### Historical Decision Audit

Input:

```text
symbol set, date range, horizon, prompt version
```

Output:

```text
action distribution, representative runs, common reasons, evidence links,
prompt/config differences
```

### Prompt Regression Audit

Input:

```text
old prompt version, new prompt version, benchmark suite
```

Output:

```text
action changes, confidence changes, risk-budget changes, report-format
changes, suspected causes
```

### Memory Retrieval Audit

Input:

```text
episode ID or run ID
```

Output:

```text
which memories were retrieved, why, where they appeared in prompts, and whether
the later outcome supported them
```

### Ticker/Horizon Profile

Input:

```text
symbol, horizon
```

Output:

```text
historical actions, known failure modes, useful strategy cards, invalidation
patterns, volatility/risk sizing notes
```

## System Architecture Implications

### Execution Graph

The LangGraph path should stay focused on producing one high-quality decision.
It should not perform heavy historical analysis inline unless the retrieval
policy specifically requires it.

Implications:

- Build retrieval packs before the run starts.
- Log every retrieved memory, strategy card, and historical episode reference.
- Keep raw audit logging separate from context retrieval.

### Evaluation Ledger

The ledger becomes the canonical index for agent-readable history.

Implications:

- Do not rely on scanning `eval_results` JSON files for routine questions.
- Normalize enough trace spans to answer common audits without opening the full
  artifact.
- Add indexes for prompt version, model version, horizon, action, symbol, and
  reward maturity.

### Prompt System

Prompts should reference structured context contracts instead of vague memory
appendices.

Implications:

- A prompt should say what kind of retrieval pack it expects.
- Agents should be told how to use retrieved history: as evidence, not as an
  instruction to copy prior decisions.
- Prompts should distinguish current evidence from historical lessons.

### Reports

Reports should serve both humans and agents.

Implications:

- Keep markdown readable for humans.
- Preserve structured labels for agent parsing: action, advisory rating,
  Alpaca action, confidence, risk budget, invalidation, review cadence.
- Make final reports cite run IDs, strategy IDs, and memory IDs where relevant.

### Web UI

The UI should expose history through summaries and drill-downs, not only raw
reports.

Implications:

- Add an action-distribution view by horizon/symbol/date.
- Add prompt-version comparison views.
- Add links from report sections to underlying run IDs and evidence spans.
- Allow markdown export of both human recommendations and Alpaca action plans.

### CLI And Automation

CLI commands should become the agent-friendly interface to history.

Recommended commands:

```bash
python -m tradingagents.eval index-runs --since 2026-01-01
python -m tradingagents.eval audit-actions --symbols LITE,SNDK,FIG --horizon position
python -m tradingagents.eval compare-prompts --suite position-core --baseline v1 --candidate v2
python -m tradingagents.eval build-retrieval-pack --symbol LITE --horizon position
python -m tradingagents.eval memory-report --symbol LITE --horizon position
```

## Storage Shape

Recommended additions to the current ledger direction:

```text
run_summaries
  run_id, symbol, trade_date, horizon, action, advisory_rating, confidence,
  prompt_version, model_provider, quick_model, deep_model, selected_analysts,
  audit_path, report_path, created_at

episode_claims
  claim_id, run_id, agent_role, claim_type, claim_text, direction, confidence,
  evidence_span_ids

episode_reasons
  reason_id, run_id, action, reason_type, reason_text, supporting_span_ids

retrieval_packs
  pack_id, episode_id, pack_type, policy_version, token_budget, created_at

retrieval_pack_items
  pack_id, item_type, item_id, rank, reason, token_estimate

strategy_cards
  strategy_id, horizon, asset_class, entry_context, required_evidence,
  invalidation, risk_budget, lifecycle_state

strategy_episode_links
  strategy_id, episode_id, link_type, reward_snapshot
```

These tables do not replace the current ledger. They make the ledger easier for
agents to query and cite.

## Anti-Patterns

Avoid these patterns:

- injecting all historical memory into every prompt
- using one global vector store as the only retrieval mechanism
- storing long prompt payloads repeatedly in every summary table
- letting LLM-generated summaries become source of truth without run IDs
- mixing high-leakage and low-leakage historical runs in benchmark reports
- changing prompts based on a small set of unresolved recent examples
- hiding Alpaca execution semantics inside advisory ratings

## Near-Term Implementation Path

1. Create a compact run index from existing audit JSON and Episode Ledger rows.
2. Add action-reason extraction for completed runs, with run ID citations.
3. Add CLI reports for action distribution and HOLD/BUY/SELL reason taxonomy.
4. Add retrieval pack builders for prompt audit, risk review, and ticker/horizon
   context.
5. Log retrieved pack items into each new episode.
6. Add benchmark suites that compare prompt versions using the same symbol/date
   sets.
7. Add Web UI views that read summaries first and open raw reports only on
   drill-down.

The detailed implementation backlog for `RUN_INDEX`, `QUALITY_INDEX`, retrieval
packs, and Memory V2 is maintained in
[Future Improvement Roadmap](future-improvement-roadmap.md).

## Design Standard

For any new durable output, ask:

- Can an agent find it without knowing the folder layout?
- Can an agent read the summary in under a few thousand tokens?
- Can the summary point back to source-of-truth artifacts?
- Can this be filtered by symbol, horizon, prompt version, model, and date?
- Can future evaluation tell whether retrieving this item helped or hurt?

If the answer is no, the artifact is not yet agent/LLM-friendly.

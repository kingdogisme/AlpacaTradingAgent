# Alpha Discovery System Concept

## Purpose

Alpha Discovery is a proposed upstream system for AlpacaTradingAgent. Its job
is to discover, rank, and explain potential ticker opportunities before they
enter the heavier ATA deep-analysis graph.

The core separation is:

- Alpha Discovery answers: "What should ATA look at next?"
- ATA answers: "Given this ticker, what is the trade-quality judgment?"

This keeps full multi-agent analysis from becoming an expensive all-market
scanner.

Alpha Discovery is not meant to be a trading engine. It is an attention
allocation system. Its primary product is a maintained opportunity basket:
which tickers, themes, and catalysts deserve scarce downstream analysis budget.

This also means a discovered ticker is not automatically a trend-following
trade. Social and news attention usually means the market is already talking
about something, but the opportunity can still take several forms:

- continuation: the market narrative is early and price has not fully caught up
- reversal: attention is crowded, exhausted, or contradicted by fundamentals
- volatility: the direction is unclear, but options or event risk are elevated
- second-order: the discussed ticker is crowded, but a supplier, competitor,
  beneficiary, or hedge is less crowded
- avoidance: the signal is noisy, stale, or low quality and should consume no
  ATA budget

The discovery layer should preserve this ambiguity. It should pass a
`direction_hint`, evidence, and caveats to ATA, not a final trade instruction.

## Design Principle

The system should be hybrid: rule-governed, LLM-assisted.

Rules should control the repeatable parts:

- scheduling
- source selection
- ticker eligibility
- deduplication
- cooldowns
- liquidity filters
- maximum daily run counts
- score weighting
- persistence
- forward-return evaluation

LLMs should handle the messy semantic parts:

- extracting tickers from unstructured social/news text
- mapping tickers to themes
- summarizing catalysts
- detecting narrative novelty
- explaining why a ticker entered or left the run list
- classifying evidence strength, crowding risk, and time sensitivity

The LLM should not be the sole source of truth for final ranking. It should
produce structured evidence that a deterministic scorer can consume.

## Maintainability And Observability Principles

Alpha Discovery should be built as a long-running research system, not as a
one-off scraper. Cron jobs only become useful if each run is reproducible,
auditable, and easy to debug days later.

Core maintainability principles:

- Every material step must write structured state, not only console text.
- Every candidate must retain the raw source pointer, extracted evidence,
  scoring components, promotion gate, risk flags, handoff, and outcome.
- Every score change must be explainable from persisted fields. If a candidate
  moves from B to A, the exact confirmation source and component delta should be
  visible.
- Every external dependency should fail softly. A broken DD, options, price, or
  news call should record an unavailable signal and should not corrupt the
  whole batch.
- Every cron command should be idempotent enough to rerun safely. Reruns should
  upsert candidates/signals by stable identifiers instead of duplicating work.
- Every production cron should have a bounded budget: max candidates,
  per-ticker cooldown, daily ATA budget, source timeouts, and output truncation.
- Every parser should have fixture tests. MCP text formats change, so parsing
  assumptions must be covered by small deterministic tests.
- Every production-facing default should be conservative. Discovery should
  prefer missing an A-list promotion over flooding ATA with noisy social names.
- Official filing facts should be treated as a quality layer, not a discovery
  source. SEC EDGAR can confirm freshness, revenue direction, margin risk, or
  balance-sheet risk, but it should not create a ticker by itself and should
  not be the only independent signal that promotes a social-only idea to A.

Required observability artifacts:

```text
DiscoveryBatch
  batch_id, sources, generated_at, config_json, status

OpportunityCandidate
  ticker, tier, alpha_score, opportunity_type, direction_hint, theme,
  catalyst, ttl, discovered_at, score_components_json, risk_flags_json,
  run_reason, rejected_reason

SourceSignal
  candidate_id, source, raw_artifact_id, source_timestamp, mentions,
  sentiment, evidence_json, raw_text_ref

Handoff
  candidate_id, run_id, status, executed_at, ATA final signal/confidence

Outcome
  candidate_id, horizon_days, raw_return, benchmark_return, alpha_return,
  MFE, MAE, resolved_at
```

Operational reports should answer:

- What did this cron run discover, reject, promote, or leave unchanged?
- Which source produced each candidate?
- Which confirmation moved the score?
- Why did an A-list gate fail?
- Which candidates consumed ATA budget?
- Which B/C/Rejected shadow candidates later worked?
- Which source/theme has positive forward alpha by horizon?

The minimum useful CLI observability surface is:

```bash
python -m cli.main cron-discover --source wsb,dd --max-candidates 25
python -m cli.main cron-confirm --tier B,C --max-candidates 25
python -m cli.main basket-list --tier A,B,C,Rejected --status open
python -m cli.main basket-report --status open
python -m cli.main basket-eval-report --status open
python -m cli.main ad-events --limit 100
python -m cli.main ad-health
python -m cli.main cron-resolve --as-of YYYY-MM-DD
```

Current implementation note: Phase 2 includes the append-only
`discovery_events` table plus `ad-events` and `ad-health` CLI commands. The
event stream records collector start/end/failure, SellTheNews MCP tool latency,
candidate scoring, confirmation decisions, dry-run/executed handoffs, and
batch-level failure states. `ad-health` summarizes the latest batches, open
basket size by tier, today's handoffs, recent event counts, and recent errors.
For tonight's cron rollout, every cron invocation should redirect stdout/stderr
to a dated log file and `ad-health` should run after each discover/confirm/run
block.

## SEC EDGAR Fundamental Confirmation

SEC EDGAR is the official historical filing source for AD/ATA fundamentals.
V1 intentionally uses structured APIs only:

- `submissions` for latest 10-K, 10-Q, and 8-K metadata.
- `companyfacts` for compact XBRL facts such as revenue, gross profit,
  operating income, net income, cash, debt, operating cash flow, and shares.

Operational contract:

- SEC does not generate candidates. It only enriches existing candidates with
  `sec_edgar_fundamental_confirmation` source signals.
- SEC flags include `recent_filing_available`, `filing_stale`,
  `revenue_acceleration`, `margin_deterioration`, `cash_debt_risk`, and
  `missing_fields:*`.
- SEC can add a small score component via `fundamental_confirmation`.
- SEC alone cannot satisfy the A-list independent confirmation gate for a
  social-only candidate. A promotion still needs price/volume, options, direct
  news, live/search news, or another non-summary confirmation.
- Reports must stay compact and cite period/end date/form/frame/source tag so
  downstream LLMs do not mix annual, quarterly, and point-in-time facts.

## AD / ATA Interface

The interface between Alpha Discovery and ATA should be an opportunity basket,
not just a ticker list. A ticker-only list loses the reason the ticker was
selected, makes reruns hard to control, and prevents later evaluation from
knowing which signal was actually tested.

Recommended basket item:

```json
{
  "candidate_id": "2026-05-13-wsb-MU-memory-001",
  "ticker": "MU",
  "asset_type": "stock",
  "tier": "A",
  "alpha_score": 0.82,
  "opportunity_type": "continuation|reversal|volatility|second_order|avoid",
  "direction_hint": "bullish|bearish|mixed|volatility|avoid",
  "theme": "Memory/Semiconductor",
  "catalyst": "Samsung strike and China delegation narrative",
  "catalyst_type": "social|news|policy|earnings|options|macro|technical|other",
  "evidence_summary": "WSB heat and ticker sentiment are both elevated.",
  "source_signals": [
    {
      "source": "sellthenews_wsb_analysis",
      "source_timestamp": "2026-05-13T08:00:00-04:00",
      "mentions": 80,
      "sentiment": "strong_bullish",
      "raw_artifact_id": "mcp://sellthenews/wsb/2026-05-13/0"
    }
  ],
  "urgency": "intraday|today|1-5d|2-10d|low",
  "ttl": "2026-05-14T16:00:00-04:00",
  "cooldown_state": "eligible|cooling_down|rerun_requires_new_evidence",
  "recommended_analysts": ["market", "social", "news", "fundamentals"],
  "run_reason": "Top eligible ticker in high-heat memory theme with cross-source sentiment.",
  "risk_flags": ["crowded_social_trade"],
  "rejected_reason": null
}
```

ATA should consume only filtered basket items. It should return an analysis
record that links back to `candidate_id` so AD can learn whether the handoff was
useful.

## System Shape

```text
MCP / Data Collectors
        |
        v
LLM Evidence Extractor
        |
        v
Theme and Ticker Graph
        |
        v
Deterministic Scoring and Filters
        |
        v
Candidate Run List
        |
        v
ATA Deep Analysis
        |
        v
Episode Ledger / Outcome Feedback
```

The feedback loop should update Alpha Discovery as well as ATA. ATA feedback is
an intermediate critic signal. Market outcomes are the final reward signal.

## Candidate Sources

The first version should focus on high-signal, low-integration-cost sources.

### Social Sources

- SellTheNews `get_wsb_analysis`
- SellTheNews `get_wsb_discussion`
- SellTheNews `get_dd_list`
- SellTheNews `get_dd_post`
- SellTheNews `search_dd`
- public Reddit samples
- StockTwits samples

### News And Event Sources

- SellTheNews `get_live_news`
- SellTheNews `search_news`
- SellTheNews `get_stock_news`
- SellTheNews `get_trump_posts`
- Google News
- Finnhub company news
- earnings calendar

### Market And Options Sources

- Alpaca price/volume data
- premarket movers
- intraday gap and relative-volume screens
- SellTheNews `get_options_data`
- gamma flip / GEX / selected Greeks where available

## First SellTheNews Workflow

`get_wsb_analysis` is a strong initial seed source because it already contains
theme-level and ticker-level summaries.

Initial extraction procedure:

1. Pull latest WSB analysis with `offset=0`.
2. Parse `Sector Heatmap`.
3. Take the top themes by heat.
4. For each theme, inspect `Representative Tickers`.
5. Cross-check those tickers against `Individual Stock Sentiment Analysis`.
6. Select the highest-mention eligible ticker per theme.
7. Keep the selected ticker's sentiment, mention count, theme, and narrative.
8. Pass the short list into secondary validation.

Example output shape:

```json
{
  "ticker": "MU",
  "theme": "Memory/Semiconductor",
  "source": "sellthenews_wsb_analysis",
  "mentions": "80+",
  "sentiment": "strong_bullish",
  "catalyst": "Samsung strike and China delegation narrative",
  "time_horizon": "1-5 trading days",
  "evidence_strength": 0.78,
  "crowding_risk": 0.65
}
```

## WSB DD Workflow

SellTheNews WSB DD is a separate discovery source from daily WSB discussion.
Daily discussion is better for heat, attention, crowding, and intraday mood. DD
posts are better for thesis discovery, second-order ideas, explicit holes,
discussion rebuttals, and fact-checkable claims.

Initial DD extraction procedure:

1. Call `get_dd_list(limit=20)` as a cheap discovery pass.
2. Filter by basic quality controls such as minimum score, minimum comments, and
   ticker eligibility.
3. For each surviving `postId`, call `get_dd_post`.
4. Extract `post_id`, `reddit_title`, `ai_title`, `tickers`,
   `ticker_sentiment`, `score`, `comments`, `posted_at`, `thesis`, `evidence`,
   `holes`, `discussion_summary`, `fact_check_status_counts`, and
   `source_urls`.
5. Use `sellthenews_wsb_dd` as the source name and
   `mcp://sellthenews/dd/{postId}` as the raw artifact id.
6. Promote to A/B only after reading the full DD post; `get_dd_list` alone never
   qualifies a candidate for A-list.

Default DD scoring should be quality-first:

- Positive evidence: supported fact-checks, clear catalyst, verifiable source
  URLs, meaningful discussion depth, and ticker sentiment consistent with the
  thesis.
- Negative evidence: unsupported or questionable fact-checks, severe holes,
  short-dated options decay, low score or low comments, and strong conflict
  between author thesis and discussion rebuttals.

DD candidates should still enter the shadow basket when rejected or left in
B/C-list so forward returns can reveal missed opportunities and source bias.
The default `opportunity_type` should be inferred from the content rather than
assumed to be `continuation`.

## LLM Responsibilities

The LLM should produce compact structured records, not long recommendations.

Recommended extraction schema:

```json
{
  "ticker": "string",
  "asset_type": "stock|etf|crypto|unknown",
  "theme": "string",
  "source": "string",
  "source_timestamp": "string",
  "mentions": "number|null",
  "sentiment": "strong_bullish|bullish|neutral|bearish|strong_bearish|mixed",
  "opportunity_type": "continuation|reversal|volatility|second_order|avoid",
  "direction_hint": "bullish|bearish|mixed|volatility|avoid",
  "catalyst": "string",
  "catalyst_type": "social|news|policy|earnings|options|macro|technical|other",
  "novelty": "high|medium|low",
  "time_sensitivity": "intraday|1-5d|2-10d|1-3m|unknown",
  "evidence_strength": "number between 0 and 1",
  "crowding_risk": "number between 0 and 1",
  "source_interpretation": "raw|llm_summary|news_article|market_data",
  "second_order_candidates": ["string"],
  "risk_flags": ["string"],
  "notes": "string"
}
```

The extractor should be conservative:

- Do not invent ticker symbols.
- Mark ambiguous symbols as `unknown`.
- Preserve bearish signals instead of converting all attention into bullish
  candidates.
- Distinguish direct catalysts from sympathy/theme spillover.
- Record conflicts between sources.
- Distinguish "market is discussing this" from "there is still alpha left".
- Mark second-order candidates separately from the crowded primary ticker.

## Rule-Based Responsibilities

The deterministic layer should decide what can actually enter the run list.

Suggested filters:

- Must be tradeable by the configured brokerage or explicitly allowed.
- Exclude low-liquidity names by default.
- Exclude ETFs unless ETF mode is enabled.
- Exclude leveraged ETFs unless explicitly enabled.
- Require at least one catalyst or one major anomaly.
- Require cross-source confirmation for lower-quality social-only signals.
- Enforce per-ticker cooldowns.
- Enforce daily maximum ATA runs.

Signals should be filtered by opportunity type:

- continuation candidates need early narrative, fresh catalyst, and price/volume
  confirmation that is not already exhausted
- reversal candidates need crowding, sentiment extremity, failed breakout, or
  contradictory evidence
- volatility candidates need options/event confirmation and should not force a
  bullish or bearish direction
- second-order candidates need a clear economic link to the primary theme

Suggested default cooldowns:

```text
Full ATA run: same ticker at most 5 times per trading day
Full ATA cooldown: 24 hours
Discovery rebuild: 1 primary daily run, plus 1 optional event-driven run
Confirmation refresh: 1-2 lightweight passes per trading day
```

## Scoring

The first scoring model should be explainable and deterministic.

```text
alpha_score =
  social_heat
+ catalyst_strength
+ catalyst_novelty
+ cross_source_confirmation
+ price_volume_confirmation
+ options_pressure
+ theme_strength
- crowding_risk
- staleness_penalty
- liquidity_penalty
- duplication_penalty
```

Every score should be decomposed into components so later evaluation can answer
which signals helped or hurt.

Scoring should be calibrated by opportunity type. A highly crowded social name
may score well as a volatility or reversal candidate while scoring poorly as a
continuation candidate. The basket should preserve both `alpha_score` and
`opportunity_type` so ATA can choose the right analysis frame.

Suggested additional components:

```text
continuation_score =
  narrative_freshness
+ catalyst_strength
+ early_price_volume_confirmation
+ source_diversity
- crowding_risk
- move_already_realized

reversal_score =
  crowding_extremity
+ failed_follow_through
+ contradictory_evidence
+ valuation_or_fundamental_tension
- borrow_or_liquidity_constraints

volatility_score =
  event_uncertainty
+ options_volume_or_iv_change
+ disagreement_between_sources
+ upcoming_catalyst_density
- stale_event_penalty

second_order_score =
  theme_strength
+ economic_link_strength
+ lower_crowding_than_primary
+ price_lag_vs_primary
- weak_link_penalty
```

## Run List Tiers

The output should not be one flat list. It should produce tiers:

- A-list: immediate ATA deep analysis, usually 3-6 tickers.
- B-list: watch for confirmation, usually 8-15 tickers.
- C-list: theme memory only, no ATA run.
- Rejected: explain why it was filtered out.

Example:

```json
{
  "batch_id": "2026-05-13-postclose",
  "generated_at": "2026-05-13T16:30:00-04:00",
  "a_list": ["MU", "NVDA", "UNH"],
  "b_list": ["TSLA", "OKLO", "ASTS", "OPEN"],
  "c_list": ["FCEL", "POET"],
  "rejected": [
    {
      "ticker": "SOXL",
      "reason": "leveraged ETF excluded by default"
    }
  ]
}
```

## Source Bias And Confirmation

SellTheNews is useful because it provides several high-leverage inputs through
one MCP, but it should not define the discovery universe by itself. The system
must explicitly model source bias.

Known bias modes:

- WSB analysis overweights popular, volatile, meme, and retail-attention names.
- Major media sources overweight large caps and may report after the move has
  already started.
- Political social feeds can create unstable policy narratives.
- MCP AI summaries are interpreted evidence, not raw market facts.
- A single convenient MCP can create availability bias: the system may rank what
  is easy to observe rather than what is most important.
- WSB DD adds author-position bias, persuasive long-form narrative bias,
  selective data risk, short-dated options time-decay risk, and low-score early
  post uncertainty.

Mitigations:

- Store whether evidence is raw text, market data, news article, or LLM summary.
- Require independent confirmation for social-only A-list candidates.
- Track source reliability by theme, ticker class, time horizon, and market
  regime.
- Keep rejected and B/C-list candidates in a shadow basket and evaluate their
  forward outcomes.
- Penalize duplicate narratives that appear in many sources but add no new
  information.
- Reserve exploration budget for non-consensus candidates so the system can
  learn what it is missing.
- Compare primary discussed tickers against second-order tickers in the same
  theme.

For the MVP, SellTheNews can be the first collector. For production use, A-list
promotion should normally require at least one non-summary confirmation signal:
price/volume, options, direct company news, sector peer movement, or another
independent source.

## Scheduling

Use `America/New_York` as the primary scheduling timezone. Avoid hard-coded UTC
offsets because daylight saving time changes.

Suggested cadence:

```text
08:15 ET  daily premarket discovery rebuild
09:25 ET  pre-open confirmation pass
15:30 ET  optional event-driven discovery only for live-news/volume shocks
16:30 ET  post-close confirmation pass
20:00 ET  evening DD/news refresh for next session
```

The system should not assume new alpha candidates appear every hour. Frequent
polling is useful for cheap source state and confirmation refresh, but basket
rebuilds should be sparse unless a true event source fires. A healthy initial
target is:

```text
Raw discoveries per day: 10-30
Deduped watchlist per day: 6-15
Full ATA runs per day: 1-5
High-conviction shortlist per day: 1-4
```

Full ATA should normally run after the pre-open confirmation pass and after the
post-close confirmation pass, with a daily budget of 5 candidate runs. Intraday
ATA runs should still require an event-driven trigger such as direct breaking
news, unusual price/volume, options pressure, or a material change in a
candidate's promotion gate.

## Evaluation Loop

Discovery must be measured separately from ATA.

There are three feedback levels:

1. Discovery feedback: did the candidate stay relevant, gain confirmation, or
   decay quickly?
2. ATA feedback: did ATA confirm the setup, reject it, change the direction, or
   identify a better risk frame?
3. Market feedback: did the ticker deliver forward alpha after costs and
   relative to the benchmark/theme?

ATA feedback is useful for learning routing quality, but it is not the final
label. A candidate can be useful even if ATA rejects it, and ATA can be
confident while the market outcome is poor. The discovery ledger should record
both.

This matters especially when A-list candidates receive repeated HOLD or SELL
judgments from ATA but later keep rising. That outcome should not be treated as
a simple Alpha Discovery failure or a simple ATA failure. It can mean several
different things:

- Alpha Discovery found a real attention/catalyst opportunity, but ATA used the
  wrong analysis frame or over-weighted valuation/fundamental caution.
- The candidate was directionally useful for a tradeable move, but did not meet
  ATA's threshold for a risk-adjusted long recommendation.
- The move was primarily momentum, positioning, squeeze, or narrative
  continuation, while ATA was evaluating it as a fundamental investment setup.
- The evaluation horizon was mismatched: ATA may have rejected a multi-day
  setup that still produced a 1-day or intraday move.
- The benchmark or theme adjustment may show the move was broad beta rather
  than idiosyncratic alpha.

The evaluation system should therefore keep four labels separate:

1. **Discovery quality**: did AD surface a ticker/theme before or during a
   meaningful market move?
2. **Routing quality**: was it worth spending ATA budget on that candidate at
   that time?
3. **ATA judgment quality**: did ATA correctly assess risk, direction, and
   setup type given the evidence it saw?
4. **Trade outcome quality**: did an executable strategy with realistic entry,
   exit, slippage, and risk limits make money?

For the current system, the best primary objective is routing quality, not raw
trading PnL. AD should learn which candidates deserved deeper analysis, which
sources and themes led to forward alpha, and which cases ATA systematically
misclassified. ATA feedback is a critic signal, while forward returns and
benchmark/theme-adjusted outcomes are the harder labels.

Useful metrics:

- discovery hit rate
- forward return after 1d, 2d, 5d, and 10d
- MFE and MAE after discovery and after ATA handoff
- benchmark-adjusted alpha
- theme-adjusted alpha where a clean peer basket exists
- theme-level hit rate
- source-level reliability
- average staleness of accepted candidates
- rejected-candidate opportunity cost
- cost per accepted candidate
- cost per profitable ATA run
- missed-winner rate among rejected and B/C-list candidates
- source contribution by opportunity type
- ATA handoff precision by analyst set and time of day
- ATA disagreement rate: A-list candidates that ATA rejected but later produced
  positive forward alpha
- false-negative cost: forward alpha missed because ATA returned HOLD/SELL or
  because the candidate never reached A-list
- false-positive cost: ATA budget spent on candidates with poor forward alpha
- horizon fit: whether the signal worked at 1d, 3d, 5d, or 10d

Each candidate should keep enough provenance to evaluate:

- source
- extraction prompt version
- scorer version
- raw evidence artifact path
- selected tier
- whether ATA actually ran
- final ATA decision
- future return
- opportunity type
- direction hint
- basket tier history
- cooldown and rerun decisions

Recommended confusion matrix:

```text
AD selected + ATA bullish + forward alpha positive  = ideal handoff
AD selected + ATA bullish + forward alpha negative  = ATA false positive or bad timing
AD selected + ATA HOLD/SELL + forward alpha positive = ATA false negative or wrong frame
AD selected + ATA HOLD/SELL + forward alpha negative = useful rejection
B/C/Rejected + forward alpha positive                = AD promotion miss
B/C/Rejected + forward alpha negative                = useful filter
```

This matrix should be computed by opportunity type. A HOLD/SELL on a
fundamental frame may still be compatible with a volatility or squeeze signal.
Likewise, a ticker can rise while still being a poor risk-adjusted long if MAE,
gap risk, liquidity, or catalyst timing made the trade unattractive.

## Memory-Enhanced Learning Architecture

Alpha Discovery is a better first target for memory-enhanced learning than ATA
because its actions are discrete budget-allocation decisions:

- which sources to query
- which themes to expand
- which tickers to include or reject
- which tier to assign
- whether to spend a full ATA run
- whether to break cooldown because new evidence arrived
- which analyst set ATA should use

Recommended memory layers:

- episodic memory: discovery batches, candidates, scores, decisions, ATA
  handoffs, and later outcomes
- theme memory: recurring narratives, continuation/failure patterns, and regime
  sensitivity
- ticker memory: past social noise, catalyst follow-through, volatility, and
  ATA usefulness
- source memory: source reliability by theme, ticker class, time horizon, and
  market regime
- negative memory: stale narratives, low-liquidity traps, pump-like patterns,
  and false confirmations
- strategy-card memory: reusable discovery patterns that can be tested and
  promoted or retired

Learning should progress in phases:

1. Deterministic rules and transparent scores.
2. Outcome-based score calibration.
3. Contextual bandit for source selection, tiering, and ATA budget allocation.
4. Learning-to-rank over basket candidates.
5. Offline reinforcement learning once enough logged decisions and shadow-basket
   outcomes exist.

The early reward target should be routing quality, not final trading PnL alone:

```text
handoff_reward =
  forward_alpha_after_handoff
+ meaningful_move_capture
+ ATA_confirmation_quality_or_useful_rejection
- ATA_false_negative_penalty
- ATA_budget_cost
- staleness_penalty
- false_positive_penalty

batch_reward =
  top_k_precision
+ ranking_ndcg
+ discovered_winner_bonus
- missed_obvious_winner_penalty
- ATA_misclassification_penalty
- duplicated_attention_penalty
- excessive_ATA_run_penalty
```

Exploration is required. Without evaluating some B-list, C-list, and rejected
candidates, the system will only learn from names it already believed in and
will reinforce its own source bias.

## MVP

The smallest useful implementation:

1. Add a discovery CLI command that calls SellTheNews WSB analysis.
2. Parse sector heatmap and individual ticker sentiment.
3. Generate structured candidate records.
4. Score and filter candidates with deterministic rules.
5. Persist the run list as JSONL or SQLite.
6. Add a runner command that sends A-list tickers into ATA.
7. Record candidate outcomes after fixed windows.

Implemented cron-friendly commands:

```bash
python -m cli.main cron-discover --source wsb,dd --max-candidates 25
python -m cli.main cron-confirm --tier B,C --max-candidates 25
python -m cli.main cron-run --tier A --max-symbols 6
python -m cli.main cron-run --tier A --max-symbols 6 --execute
python -m cli.main cron-resolve --as-of YYYY-MM-DD
python -m cli.main basket-list --tier A,B --status open
python -m cli.main basket-report --status open
python -m cli.main basket-eval-report --status open
python -m cli.main ad-events --limit 100
python -m cli.main ad-health
python -m cli.main cron-schedule
```

Phase 2 keeps scoring deterministic. A-list promotion requires at least one
independent confirmation source, such as direct company news, ticker-matched
search/live news, options pressure, or price/volume confirmation. Social-only
WSB heat remains capped at B-list. Price/volume confirmation checks relative
volume, 1-day move, gap, and overextension so the system does not blindly chase
already-exhausted moves.

For the first 24h production regression, run AD in discovery/confirmation and
`cron-run` dry-run mode only. Enable `cron-run --execute` only after reviewing
`ad-health`, `ad-events --status error`, `basket-report`, and the dry-run
candidates. A broken collector should soft-fail and log `collector_failed`
rather than kill the entire batch.

## Non-Goals For The First Version

- Do not train a model before collecting labeled outcomes.
- Do not let the LLM directly submit orders.
- Do not run full ATA on every discovered ticker.
- Do not treat WSB attention as bullish by default.
- Do not mix discovery evaluation with ATA final-decision evaluation.

## Research Directions

After the MVP has several weeks of outcomes, consider:

- learning-to-rank over discovery features
- theme graph propagation for second-order opportunities
- source reliability weighting
- LLM-generated alpha factor candidates
- graph neural networks over ticker/theme/news relationships
- reinforcement learning for run-list budget allocation
- personalized watchlists by sector, liquidity, and trading horizon

The most pragmatic first learning target is not model weights. It is routing:
which candidates deserve expensive ATA analysis, at what cadence, and with
which analyst set.

## Research Article Signals

n8n/Substack research articles are first-class `SourceSignal` inputs, not just notification text. The ingest path classifies every article into a small schema: `single_ticker_dd`, `thematic_dd`, `news_digest`, `portfolio_update`, `macro_note`, or `other`. The classifier extracts primary and secondary tickers, article depth, novelty, conviction, source quality, direction hint, thesis, risks, watch items, and horizon.

Research articles act as confirmation signals by default. Deterministic scoring computes `research_boost = source_quality * depth_score * novelty_score * conviction_score`, capped at `alpha_discovery_research_boost_max` by default. High-quality, trusted `single_ticker_dd` can use a higher cap and may pass `passed_research_dd_gate`, allowing a clearly identified primary ticker to reach tier A from one strong article. Thematic DD can create or strengthen B-tier theme exposure, while secondary tickers are capped lower and cannot independently A-promote. News digests are retained as raw events/enriched context and do not boost all mentioned tickers.

Every applied article writes both records: the raw `n8n_ingest_events` row for replay/debugging, and a `SourceSignal(source="research_article")` attached to the affected candidate. Candidate score components must remain explainable with `research_article_boost`, `research_article_count`, `research_quality_max`, `confirmation_sources`, and `promotion_gate`.

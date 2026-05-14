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
Full ATA run: same ticker at most twice per trading day
Full ATA cooldown: 6 hours
Discovery scan: every 30-60 minutes during active windows
Run-list rebuild: 3-5 times per trading day
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
08:00 ET  premarket discovery
09:20 ET  pre-open confirmation
10:15 ET  post-open confirmation
12:30 ET  midday light refresh
15:10 ET  power-hour scan
16:30 ET  post-close discovery
20:00 ET  evening preparation
```

Only a subset of these should trigger full ATA analysis. A healthy initial
target is:

```text
Raw discoveries per day: 30-80
Deduped watchlist per day: 12-25
Full ATA runs per day: 5-12
High-conviction shortlist per day: 3-6
```

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

Useful metrics:

- discovery hit rate
- forward return after 1d, 2d, 5d, and 10d
- benchmark-adjusted alpha
- theme-level hit rate
- source-level reliability
- average staleness of accepted candidates
- rejected-candidate opportunity cost
- cost per accepted candidate
- cost per profitable ATA run
- missed-winner rate among rejected and B/C-list candidates
- source contribution by opportunity type
- ATA handoff precision by analyst set and time of day

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
+ ATA_confirmation_quality
- ATA_budget_cost
- staleness_penalty
- false_positive_penalty

batch_reward =
  top_k_precision
+ ranking_ndcg
+ discovered_winner_bonus
- missed_obvious_winner_penalty
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

Potential commands:

```bash
python -m cli.main cron-discover --source wsb --top-sectors 10 --per-sector 1
python -m cli.main cron-run --tier a --max-symbols 6 --analysts market,social,news,macro
python -m cli.main cron-once --source wsb --run-tier a
```

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

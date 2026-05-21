# Future Improvement Roadmap

## Purpose

本文档把当前架构上最值得继续投入的方向整理成 implementation-ready
backlog。它不是承诺立即实现所有功能，而是为后续 PR、AI agent 任务分解、
测试设计和验收提供稳定规格。

核心原则：

- 所有新增 artifact 都必须有 stable ID。
- 所有摘要都必须能指回 source-of-truth artifact。
- AI agent 常规入口应是 index、summary、retrieval pack 或 CLI JSON，而不是
  直接扫描 raw audit JSON。
- 每个方向都必须有明确测试策略和验收标准。

## Recommended Priority

1. Agent-readable Run Index / Retrieval Packs
2. Memory V2
3. Benchmark Suites / Prompt Regression
4. Data Quality V2 / Cross-source Reconciliation
5. Portfolio / Risk Simulation Layer
6. Critic Pipeline / Failure Taxonomy
7. Operational Hardening

第一阶段建议只聚焦以下可落地基础设施：

- `RUN_INDEX`
- `QUALITY_INDEX`
- retrieval pack builder
- CLI JSON 输出
- index/retrieval contract 测试

## 1. Agent-readable Run Index / Retrieval Packs

### Goal

让开发者和 AI agent 可以从稳定、短小、可查询的索引入口理解历史 run，而不是
把 raw audit JSON 当作常规调试入口。

### Why It Matters

当前 run audit 保留了完整事实，但体积大、结构深、噪音多。AI agent 如果每次都
读取全量 JSON，会浪费上下文并增加误读概率。`RUN_INDEX`、`QUALITY_INDEX` 和
retrieval pack 可以把常见问题变成稳定查询：这个 run 的结论是什么、用了哪些
证据、哪些数据质量风险影响了结论、需要打开哪个 artifact 深挖。

### Proposed Capability

- 新增 `RUN_INDEX`：一行描述一个 run 的核心身份、配置、最终动作和 artifact
  指针。
- 新增 `QUALITY_INDEX`：按 run/tool/source 聚合数据质量状态、flags、fallback
  和 stale 风险。
- 新增 retrieval pack builder：按用途生成小型上下文包，例如
  `ticker_horizon_pack`、`risk_review_pack`、`prompt_audit_pack`。
- 新增 CLI 查询入口：默认输出 agent-readable JSON，不展开 raw output。
- 所有 retrieval pack 写回 run audit 或 episode record，记录哪些历史内容被注入
  到 agent 上下文。

### Data / API Shape

```json
{
  "run_id": "run_20260521_AAPL_position_001",
  "symbol": "AAPL",
  "trade_date": "2026-05-21",
  "horizon": "position",
  "status": "completed",
  "final_action": "HOLD",
  "confidence": 0.62,
  "config_hash": "cfg_7d31",
  "audit_ref": "audit:run_20260521_AAPL_position_001",
  "decision_ref": "decision:run_20260521_AAPL_position_001",
  "quality_index_ref": "quality_index:run_20260521_AAPL_position_001"
}
```

```json
{
  "pack_id": "retrieval_pack:AAPL:position:20260521:risk_review:v1",
  "pack_type": "risk_review",
  "source_refs": [
    "run_index:run_20260521_AAPL_position_001",
    "quality_index:run_20260521_AAPL_position_001",
    "evidence:tool_call:17"
  ],
  "token_budget": 4000,
  "items": [
    {
      "item_id": "pack_item:001",
      "kind": "quality_risk",
      "summary": "Daily OHLCV source was stale; final confidence should be capped.",
      "source_ref": "quality_event:tool_call:17"
    }
  ]
}
```

Recommended CLI:

```bash
python -m cli.main run-index --symbol AAPL --format json
python -m cli.main quality-index --run-id run_20260521_AAPL_position_001 --format json
python -m cli.main retrieval-pack --type risk_review --run-id run_20260521_AAPL_position_001 --format json
```

### Testing Plan

- Unit test index builder against fixed audit fixtures.
- Unit test `QUALITY_INDEX` counts against mixed pass/warn/fail/unknown fixtures.
- Unit test retrieval pack token budget, stable IDs and source references.
- CLI contract tests for JSON top-level fields and no default raw-output
  expansion.
- Regression test that a missing optional artifact creates a warning item, not
  a crash.

### Acceptance Criteria

- Every completed run can be listed from `RUN_INDEX`.
- Every data-quality event is reachable from `QUALITY_INDEX`.
- Every retrieval pack item has `item_id`, `source_ref`, `kind` and `summary`.
- CLI JSON contract is stable enough for AI agent consumption.
- An agent can answer "where should I look next?" without opening raw audit
  JSON.

### Dependencies / Risks

- Depends on stable audit `run_id` and tool-call `artifact_ref`.
- Risk: index staleness if raw audit and derived index update paths diverge.
  Mitigation: make index generation deterministic and testable from source
  audit fixtures.

## 2. Memory V2

### Goal

把 memory 从自由文本反思升级为 outcome-backed、可审计、可提升/降级的决策输入。

### Why It Matters

未经治理的 memory 会变成越来越长的 prompt appendix，并可能把未验证经验注入到
未来决策。Memory V2 应该让系统知道：某条经验从哪里来、被哪些 episode 支持、
什么时候被检索、检索后是否改善了结果，以及何时应该降级或废弃。

### Proposed Capability

- 新增 memory candidate：由 run、critic、reward 或人工标注产生，默认不是已信任
  memory。
- 新增 promotion/demotion lifecycle：只有被 resolved outcome 或重复证据支持的
  candidate 才能提升为 promoted memory。
- 新增 retrieval audit：每次注入 memory 都记录到 episode，后续可做 memory-on
  vs memory-off 对比。
- 新增 memory ablation：比较无 memory、episodic only、semantic only、
  procedural only、asset profile 和 full memory 的表现。
- 新增 outcome-backed memory lifecycle：当 reward 或风险指标反向时自动产生
  demotion candidate。

### Data / API Shape

```json
{
  "memory_id": "memory:AAPL:position:lesson:00042",
  "state": "candidate",
  "memory_type": "asset_lesson",
  "symbol": "AAPL",
  "horizon": "position",
  "claim": "When source freshness fails, cap confidence even if analyst consensus is bullish.",
  "supporting_refs": [
    "episode:run_20260521_AAPL_position_001",
    "quality_event:tool_call:17"
  ],
  "promotion_score": 0.0,
  "created_by": "critic:v1",
  "created_at": "2026-05-21T18:40:00Z"
}
```

```json
{
  "retrieval_id": "memory_retrieval:run_20260521_AAPL_position_001:0001",
  "run_id": "run_20260521_AAPL_position_001",
  "memory_id": "memory:AAPL:position:lesson:00042",
  "retrieval_policy": "ticker_horizon_recent_promoted_v1",
  "used_in_agent": "risk_manager",
  "source_ref": "memory:AAPL:position:lesson:00042"
}
```

### Testing Plan

- Unit tests for candidate creation, promotion, demotion and rejection states.
- Retrieval-policy tests using fixed symbol/horizon/regime fixtures.
- Audit tests confirming every retrieved memory is recorded with stable ID.
- Ablation report tests for memory policy variants.
- Backward-compatibility tests that old runs without memory fields still load.

### Acceptance Criteria

- Raw reflection is never treated as promoted memory by default.
- Every promoted memory cites supporting episode or artifact refs.
- Every retrieval is logged and can be evaluated after reward resolution.
- Memory ablation can compare at least `none`, `episodic`, `semantic` and
  `full` policies.

### Dependencies / Risks

- Depends on Episode Ledger and reward resolution.
- Risk: memory promotion becomes too conservative and yields low recall.
  Mitigation: keep candidates queryable even before promotion, but label them
  clearly as untrusted.

## 3. Benchmark Suites / Prompt Regression

### Goal

建立固定、可重复的 benchmark suites，用来比较 prompt、model、config 和 memory
policy 的行为差异。

### Why It Matters

交易 agent 的 prompt 改动很容易造成看似更聪明但实际更不稳定的行为。没有固定
benchmark，就无法判断一个改动是改善了 action quality、confidence calibration
和 quality-gate 行为，还是只是改变了措辞。

### Proposed Capability

- 定义固定 benchmark suites：symbol、trade_date、horizon、leakage policy、
  expected available sources。
- 输出 prompt/model/config 对比报告：action diff、confidence diff、
  evidence coverage diff、quality-gate diff。
- 对 final decision 做结构化 diff：BUY/SELL/HOLD/LONG/SHORT、confidence、
  thesis、invalidation、risk budget。
- 对 analyst report 做行为 diff：关键 evidence 是否缺失、是否使用 stale
  evidence、是否违反软门禁。
- 支持 baseline promotion：只有通过 benchmark 和 resolved reward 标准的变体
  才能成为新默认。

### Data / API Shape

```json
{
  "suite_id": "benchmark:swing:large_cap:v1",
  "cases": [
    {
      "case_id": "benchmark_case:AAPL:2026-01-05:swing",
      "symbol": "AAPL",
      "trade_date": "2026-01-05",
      "horizon": "swing",
      "leakage_policy": "point_in_time"
    }
  ]
}
```

```json
{
  "comparison_id": "prompt_regression:trader:v3_vs_v4:20260521",
  "baseline_ref": "prompt_variant:trader:v3",
  "candidate_ref": "prompt_variant:trader:v4",
  "summary": {
    "action_changed": 7,
    "confidence_median_delta": -0.04,
    "quality_gate_violations": 0
  },
  "case_diffs_ref": "artifact:prompt_regression_case_diffs:20260521"
}
```

### Testing Plan

- Fixture-based tests for suite loading and deterministic case ordering.
- Golden JSON tests for prompt-regression output contract.
- Unit tests for action/confidence/quality-gate diff.
- Integration tests with mocked tools and fixed LLM outputs.
- Leakage-policy tests to ensure historical suites do not call live-only
  sources by default.

### Acceptance Criteria

- A developer can run one command to compare baseline vs candidate prompt.
- Reports include action, confidence and quality-gate deltas.
- Every changed decision cites case ID and artifact refs.
- Historical benchmark suites are deterministic and point-in-time safe.

### Dependencies / Risks

- Depends on run index, quality index and structured final-decision parsing.
- Risk: benchmark cases become stale or too narrow. Mitigation: version suites
  and maintain separate smoke, regression and stress suites.

## 4. Data Quality V2 / Cross-source Reconciliation

### Goal

从单源 freshness/validator 扩展到跨源一致性检查和 source reliability score。

### Why It Matters

Data Quality v1 能指出单个工具输出是否 stale、empty 或 fallback，但很多错误只有
跨源比较才能发现。例如价格源最新 close 偏差、财务指标与 SEC official facts
冲突、新闻发布时间缺失或 macro release 与 observation date 混淆。

### Proposed Capability

- 价格 reconciliation：比较 Alpaca、yfinance、Alpha Vantage 或其他价格源的
  latest close/quote，超过阈值标记 `cross_source_price_mismatch`。
- 财务 reconciliation：SEC EDGAR official facts 优先，Finnhub/Alpha Vantage
  只能补充，不能覆盖官方事实。
- 新闻 reconciliation：按 source timestamp、published timestamp、ticker
  relevance、sample_count 和 duplicate rate 做一致性检查。
- Macro reconciliation：区分 release recency 和 series latest observation date。
- Source reliability score：按 source、dataset_type、symbol/asset class 维护
  近期 pass/warn/fail/fallback 统计，作为软门禁和 debug 排序信号。

### Data / API Shape

```json
{
  "reconciliation_id": "recon:AAPL:price_bars:20260521:close:v1",
  "symbol": "AAPL",
  "dataset_type": "price_bars",
  "checks": [
    {
      "check_id": "close_delta_pct",
      "primary_source": "alpaca_bars",
      "comparison_source": "yfinance_bars",
      "primary_value": 192.31,
      "comparison_value": 192.88,
      "delta_pct": 0.296,
      "status": "pass"
    }
  ],
  "source_refs": ["quality_event:tool_call:17", "quality_event:tool_call:18"]
}
```

```json
{
  "source_reliability_id": "source_reliability:alpaca_bars:price_bars:30d",
  "source_id": "alpaca_bars",
  "dataset_type": "price_bars",
  "window": "30d",
  "pass_rate": 0.96,
  "fallback_rate": 0.02,
  "critical_fail_count": 1,
  "updated_at": "2026-05-21T19:00:00Z"
}
```

### Testing Plan

- Unit tests for price mismatch thresholds and missing secondary source
  behavior.
- SEC precedence tests ensuring supplemental fundamentals cannot overwrite
  official facts.
- News timestamp and ticker relevance fixture tests.
- Macro fixture tests for release date vs observation date.
- Reliability-score aggregation tests over fixed quality event fixtures.

### Acceptance Criteria

- Cross-source checks create warn flags without interrupting the run.
- Critical mismatches are visible in quality index and final risk limitations.
- SEC official facts remain canonical when conflicting supplemental data exists.
- Reliability scores are reproducible from stored quality events.

### Dependencies / Risks

- Depends on Data Quality v1 event retention and stable source IDs.
- Risk: false positives from market close timing, currency, split adjustment or
  delayed feeds. Mitigation: encode dataset-specific normalization and trading
  calendar rules before comparing values.

## 5. Portfolio / Risk Simulation Layer

### Goal

把单标的 advisory decision 扩展到 portfolio-aware 风险评估和模拟执行约束。

### Why It Matters

单个 BUY/HOLD/SELL 结论无法回答组合层面的问题：已有仓位是否过度集中、相关性
是否放大风险、slippage 是否吞噬收益、drawdown 是否要求缩小 size。没有
portfolio layer，final decision 容易在单标的上看起来合理，但在账户层面不可执行。

### Proposed Capability

- Exposure report：按 symbol、sector、asset class、factor 和 direction 汇总风险。
- Correlation report：用历史 returns 或用户指定模型估计相关性和集中度。
- Slippage and cost model：按 asset class、liquidity、order type 和 size bucket
  估算执行成本。
- Drawdown-aware sizing：把最大回撤、波动、risk budget 和 confidence 共同映射到
  position-size bucket。
- Multi-position risk report：在 final decision 前生成 portfolio impact summary。

### Data / API Shape

```json
{
  "portfolio_risk_id": "portfolio_risk:acct_default:run_20260521_AAPL_position_001",
  "run_id": "run_20260521_AAPL_position_001",
  "portfolio_snapshot_ref": "portfolio_snapshot:acct_default:20260521T190000Z",
  "candidate_action": {
    "symbol": "AAPL",
    "side": "buy",
    "size_bucket": "small"
  },
  "risk_summary": {
    "gross_exposure_delta": 0.04,
    "sector_exposure_delta": 0.03,
    "estimated_slippage_bps": 8,
    "drawdown_size_cap": "small"
  }
}
```

### Testing Plan

- Unit tests for exposure aggregation and symbol/sector mapping.
- Correlation fixture tests with deterministic return matrices.
- Slippage model tests for size and liquidity buckets.
- Sizing tests for confidence, drawdown and volatility interactions.
- Mocked integration test where final decision is downgraded by portfolio risk.

### Acceptance Criteria

- Every executable recommendation includes portfolio impact fields or explicitly
  states that portfolio context is unavailable.
- Position size cannot increase when drawdown or concentration constraints fail.
- Risk report cites data sources and portfolio snapshot refs.
- Simulation layer can run without placing real orders.

### Dependencies / Risks

- Depends on portfolio snapshot availability and account abstraction.
- Risk: overfitting sizing rules before enough outcomes exist. Mitigation:
  start with deterministic constraints and only later introduce learned sizing.

## 6. Critic Pipeline / Failure Taxonomy

### Goal

新增 critic pipeline 用于诊断失败原因、提取 evidence spans 和生成 memory
candidates，但不把 critic 当作 reward source。

### Why It Matters

LLM critic 可以帮助解释错误，但不能重新定义交易是否成功。Reward 应由市场结果
和风险指标决定；critic 只应产出结构化诊断，帮助开发者定位失败类型并生成待验证
改进项。

### Proposed Capability

- Critic 只读 episode、decision、reward、quality index 和 selected evidence spans。
- 输出 failure tags：data_error、stale_evidence、reasoning_gap、
  synthesis_error、risk_control_error、execution_constraint_missing 等。
- 输出 evidence spans：每个 failure tag 指向具体 run/tool/report/ref。
- 输出 memory candidates：候选经验默认进入 Memory V2 candidate 状态。
- 支持 critic ablation：no critic、critic diagnostics only、critic-derived
  candidates、promoted memory。

### Data / API Shape

```json
{
  "critic_record_id": "critic_record:run_20260521_AAPL_position_001:v1",
  "run_id": "run_20260521_AAPL_position_001",
  "critic_version": "critic:v1",
  "failure_tags": [
    {
      "tag": "stale_evidence",
      "severity": "medium",
      "evidence_refs": ["quality_event:tool_call:17"],
      "rationale": "Final confidence did not clearly account for stale price bars."
    }
  ],
  "memory_candidate_refs": ["memory_candidate:run_20260521_AAPL_position_001:001"]
}
```

### Testing Plan

- Schema tests for critic record and failure tags.
- Fixture tests where known stale evidence creates `stale_evidence`.
- Tests ensuring critic cannot mutate reward records or promoted memory directly.
- Evidence-span tests requiring every tag to cite source refs.
- Ablation-report tests comparing critic pipeline variants.

### Acceptance Criteria

- Critic output is diagnostic only and cannot change deterministic reward.
- Every failure tag has evidence refs.
- Every memory candidate created by critic remains unpromoted until Memory V2
  rules approve it.
- Reports can aggregate failure taxonomy across benchmark suites.

### Dependencies / Risks

- Depends on structured reward records, quality index and evidence refs.
- Risk: critic hallucination. Mitigation: require cited refs and reject records
  with missing or invalid evidence spans.

## 7. Operational Hardening

### Goal

提升外部 provider、依赖升级、artifact retention 和 checkpoint compatibility 的
长期可维护性。

### Why It Matters

数据质量和 agent 行为不仅受代码影响，也受 provider 健康、第三方依赖、缓存策略
和 artifact 生命周期影响。Operational hardening 可以把隐性运行风险显式化，减少
线上排障成本。

### Proposed Capability

- Provider health：周期性外部 smoke tests，按 provider/source_id 记录 latency、
  status、quota、schema drift 和 sample freshness。
- External smoke：需要真实 credential 的测试独立于 deterministic unit suite，
  用 `RUN_EXTERNAL_TESTS=1` 启用。
- Dependency warning tracker：记录并分类 deprecation warnings，例如
  `websockets.legacy` 和 LangGraph checkpoint serializer compatibility warning。
- Checkpoint serializer compatibility：为 checkpoint read/write 建立版本化 fixture，
  避免依赖升级破坏历史恢复。
- Artifact retention：定义 raw audit、index、quality events、retrieval packs、
  benchmark outputs 的保留周期和压缩策略。

### Data / API Shape

```json
{
  "provider_health_id": "provider_health:alpaca_bars:20260521T190000Z",
  "source_id": "alpaca_bars",
  "dataset_type": "price_bars",
  "status": "pass",
  "latency_ms": 482,
  "freshness_status": "pass",
  "schema_status": "pass",
  "sample_ref": "artifact:provider_health_sample:alpaca_bars:20260521T190000Z"
}
```

```json
{
  "dependency_warning_id": "dependency_warning:langgraph_allowed_objects:20260521",
  "package": "langgraph",
  "category": "pending_deprecation",
  "first_seen": "2026-05-21",
  "status": "tracked",
  "owner": "platform",
  "resolution_ref": null
}
```

### Testing Plan

- External smoke command registration tests that skip cleanly without
  credentials.
- Provider health fixture tests for pass/warn/fail summaries.
- Warning tracker tests for stable grouping and deduplication.
- Checkpoint serializer read/write compatibility tests with versioned fixtures.
- Artifact-retention dry-run tests to verify what would be archived or deleted.

### Acceptance Criteria

- Provider health can be inspected without opening production logs.
- External tests never run accidentally in deterministic CI.
- Dependency warnings have tracked status and owner.
- Historical checkpoints remain readable across supported dependency versions.
- Artifact retention can run in dry-run mode with stable JSON output.

### Dependencies / Risks

- Depends on credential management and CI separation between deterministic and
  external tests.
- Risk: operational checks become noisy. Mitigation: group by source ID,
  dataset type and owner, and only page on critical provider failures.

## Backlog Boundary

本文档只定义后续改进方向和验收规格。除第一阶段建议项外，不要求一次性实现全部
run index、memory table、benchmark suite、portfolio simulation 或 critic
pipeline。后续实现应保持小步提交：先建立 stable contract，再接入更多数据源、
UI 面板和自动化报告。

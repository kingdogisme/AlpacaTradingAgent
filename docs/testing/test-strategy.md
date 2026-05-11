# AlpacaTradingAgent Test Strategy

## Summary

The default quality gate is local and deterministic. It validates the core chain
`config -> dataflows -> llm_clients -> agents -> graph -> cli/webui` without
real Alpaca, LLM, news, or market-data calls.

## Test Pyramid

- Unit tests: highest volume. Cover pure helpers, schemas, config precedence,
  ticker conversion, agent state transitions, final action parsing, and UI/CLI
  helper rendering.
- Mocked integration tests: exercise LangGraph setup and `TradingAgentsGraph`
  propagation with fake LLM clients, fake compiled graphs, temporary logs, and
  mocked checkpoints.
- External smoke tests: optional only. Reserved for real Alpaca/LLM/provider
  connectivity checks and skipped unless `RUN_EXTERNAL_TESTS=1`.

## Mock Boundaries

- LLMs: replace with fake `.invoke`, `.bind_tools`, and structured-output
  fallbacks. Do not call provider SDK network paths in deterministic tests.
- Alpaca and market data: patch client factories or public helpers such as
  `AlpacaUtils.get_stock_data`, `get_latest_quote`, `place_market_order`, and
  `close_position`.
- News/search providers: patch discovery and tool outputs. Deterministic tests
  must not call `requests`, OpenAI web search, Finnhub, CoinDesk, Google News,
  Reddit, FRED, or yfinance unless the call itself is mocked.
- Filesystem: write only to pytest `tmp_path` for results, cache, checkpoints,
  and memory logs.

## CI Gates

- Install `requirements.txt`.
- Run `python3 -m pytest tests/unit tests/integration/mocked -q`.
- Fail on unknown pytest markers or accidental external network access.
- Do not require API keys in PR validation.

## External Smoke Policy

External tests live under `tests/smoke` and must be marked `external`.
They are for manual or scheduled credentialed environments only:

```bash
RUN_EXTERNAL_TESTS=1 python3 -m pytest tests/smoke -q
```

Smoke tests should verify provider reachability and one minimal happy path, not
duplicate deterministic unit coverage.


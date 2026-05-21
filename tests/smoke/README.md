# External Smoke Tests

This directory is reserved for tests that intentionally call real services such
as Alpaca, OpenAI-compatible LLMs, news providers, or market-data endpoints.

Rules:

- Mark every external test with `@pytest.mark.external` and, when it opens a
  socket directly, `@pytest.mark.network`.
- Default CI and local deterministic runs must skip this directory.
- Run external smoke tests only with explicit credentials and
  `RUN_EXTERNAL_TESTS=1`.

Example:

```bash
RUN_EXTERNAL_TESTS=1 python3 -m pytest tests/smoke -q
```

Current smoke coverage is read-only:

- SellTheNews stock-news MCP, enabled by `SELLTHENEWS_API_KEY` or `SELLTHENEWS_BASE_URL`.
- Alpha Vantage MCP company overview, enabled by `ALPHA_VANTAGE_API_KEY`.
- SEC EDGAR public fundamentals, enabled by a real `SEC_EDGAR_USER_AGENT`.
- Alpaca account read-only check, enabled by `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`.
- OpenAI minimal response check, enabled by `OPENAI_API_KEY` or a local
  OpenAI-compatible proxy URL via `OPENAI_SMOKE_BASE_URL`, `OPENAI_BASE_URL`,
  or `TRADINGAGENTS_LLM_BACKEND_URL`.

These tests must not submit orders or run the full trading graph.

External E2E is intentionally gated separately because it runs the graph and
can spend more LLM/API budget:

```bash
RUN_EXTERNAL_TESTS=1 RUN_EXTERNAL_E2E_TESTS=1 python3 -m pytest tests/smoke/test_external_e2e.py -q
```

The E2E smoke requires `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, and either
`OPENAI_API_KEY` or a local OpenAI-compatible proxy URL via
`EXTERNAL_E2E_LLM_BACKEND_URL`, `TRADINGAGENTS_LLM_BACKEND_URL`, or
`OPENAI_BASE_URL`. It runs a minimal market-only graph path and patches Alpaca
order methods to fail if any live order path is reached.

Local proxy example:

```bash
RUN_EXTERNAL_TESTS=1 RUN_EXTERNAL_E2E_TESTS=1 \
EXTERNAL_E2E_LLM_BACKEND_URL=http://127.0.0.1:4000/v1 \
EXTERNAL_E2E_QUICK_MODEL=gpt-4.1-mini \
EXTERNAL_E2E_DEEP_MODEL=gpt-4.1-mini \
python3 -m pytest tests/smoke/test_external_e2e.py -q
```

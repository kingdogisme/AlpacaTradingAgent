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


# AlpacaTradingAgent Test Layout

The deterministic suite is organized by architecture layer:

- `tests/unit/config`: config state, env precedence, model registry parameters.
- `tests/unit/dataflows`: ticker formatting, safe paths, Alpaca fallback/execution rules, technical brief schemas, market hours.
- `tests/unit/llm_clients`: provider factories, missing-key errors, provider-specific runtime params, structured-output fallback.
- `tests/unit/agents`: prompt/template contracts, analyst tool selection, debate state updates, trader/research/risk manager action contracts.
- `tests/unit/graph`: state propagation, conditional routing, signal parsing, checkpoints, audit logging.
- `tests/unit/webui` and `tests/unit/cli`: pure UI/CLI helpers and rendering contracts.
- `tests/integration/mocked`: local mocked graph/WebUI/CLI flows with no external services.
- `tests/smoke`: reserved for explicit external-service smoke tests.

## Running Tests

Create a local environment and install project dependencies before running the
suite. CI uses a full dependency environment from `requirements.txt`; a bare
system `python3` is not expected to collect every test module successfully.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt pytest
```

Fast local deterministic suite:

```bash
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/integration/mocked -q
```

Full default deterministic suite:

```bash
.venv/bin/python -m pytest -q
```

External smoke tests are skipped by default and must be explicitly enabled:

```bash
RUN_EXTERNAL_TESTS=1 .venv/bin/python -m pytest tests/smoke -q
```

## Mocking Rules

- Unit and mocked integration tests must not call real Alpaca, LLM, news, or market-data APIs.
- `tests/conftest.py` sets deterministic environment defaults and blocks network access unless a test is marked `external` or `network` and `RUN_EXTERNAL_TESTS=1`.
- Use fake LLMs, fake tools, and temporary `results/cache/memory` paths for agent and graph tests.
- New tests should prefer pytest fixtures, but existing `unittest.TestCase` tests are intentionally supported.

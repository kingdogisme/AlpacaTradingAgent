# AlpacaTradingAgent: Auditable Multi-Agent Market Research Framework

> **AlpacaTradingAgent** is evolving from a trading-first Alpaca execution app into an auditable multi-agent market research and decision-intelligence framework.
>
> The project is inspired by the original [TradingAgents](https://github.com/TauricResearch/TradingAgents) framework by Tauric Research, but its current focus is decision quality: structured agent outputs, traceable research workflows, evaluation ledgers, delayed rewards, critic diagnostics, and future memory/learning infrastructure. Alpaca execution and crypto support remain available, but they are now secondary capabilities rather than the core product goal.
> 
> **Disclaimer**: This project is provided solely for educational and research purposes. It is not financial, investment, or trading advice. Trading involves risk, and users should conduct their own due diligence before making any trading decisions.

<div align="center">

🧠 [Project Focus](#project-focus) | 🧪 [Evaluation Foundation](#evaluation-foundation) | 🔬 [Research Workflow](#research-workflow) | ⚡ [Installation](#installation-and-setup) | 🌐 [Web Interface](#web-ui-usage) | 📦 [Package Usage](#alpacatradingagent-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

## Project Focus

The project goal is no longer "place trades from an LLM recommendation as quickly as possible." The goal is to build an agent research system whose decisions can be inspected, compared, scored, and eventually improved with evidence.

Primary priorities:

- High-quality multi-agent market research
- Structured and explainable final decisions
- Durable audit logs and normalized trace spans
- Deterministic delayed reward evaluation
- Experiment comparison across model, prompt, horizon, analyst set, and memory policy
- Critic diagnostics and governed memory candidates
- Offline data export for later supervised learning, contextual bandits, or offline RL

Secondary capabilities:

- Alpaca paper/live execution from explicit final actions
- Position and order visibility in the Web UI
- Stock and crypto analysis inputs
- Scheduling and auto-execution controls for controlled experiments

Alpaca execution should be treated as an optional downstream adapter. The core artifact is the research trajectory and evaluated decision record.

## Enhanced Features

### 🔬 **Research-Oriented Multi-Agent System**
- **Analyst Team**: Market, social sentiment, news, fundamentals, and macro analysts collect complementary evidence
- **Research Debate**: Bull and bear researchers stress-test the evidence before the research manager synthesizes a view
- **Trader Plan**: Converts research into horizon-aware thesis, action, invalidation, risk budget, and position plan
- **Risk Debate**: Risk agents review aggressive, conservative, and balanced views before the final portfolio decision
- **Parallel Execution**: Analysts can run simultaneously with configurable pacing to control latency and API pressure
- **Horizon Awareness**: Supports `swing`, `position`, and `trend` research horizons with different evidence and review cadence expectations

### 🧠 **Multi-Provider LLM Runtime**
- **Default OpenAI GPT-5.4 Path**: Uses `gpt-5.4-mini` for quick agents and `gpt-5.4` for deeper manager/trader agents
- **Provider Choice**: Supports OpenAI, local OpenAI-compatible endpoints, Google Gemini, Anthropic Claude, xAI, DeepSeek, Qwen, GLM, OpenRouter, Ollama, and Azure OpenAI
- **Provider-Specific Controls**: Preserves GPT reasoning controls, Gemini thinking level, Claude effort, custom model IDs, and Azure deployment names
- **Local Compatibility**: `OPENAI_USE_LOCAL` and `OPENAI_BASE_URL` continue to route core LLM calls to a local OpenAI-compatible backend

### 🧾 **Structured Decisions, Memory, and Resume**
- **Structured Final Action**: Final decisions preserve `BUY/HOLD/SELL` or `LONG/NEUTRAL/SHORT` for evaluation and optional execution
- **Advisory Ratings**: Upstream-style ratings are treated as metadata only and never directly trigger Alpaca orders
- **Structured Output Fallback**: Research Manager, Trader, and Risk Manager use structured schemas where supported and gracefully retry as free text otherwise
- **Persistent Decision Log**: Completed decisions are written to a markdown memory log and later resolved with realized returns and reflections
- **Checkpoint Resume**: Optional per-symbol SQLite checkpoints allow failed LangGraph runs to resume while successful runs clean up automatically
- **Safe Paths**: Report, cache, checkpoint, and log paths use safe ticker components, including crypto symbols like `BTC/USD -> BTC_USD`

### 🧪 **Evaluation-To-Learning Foundation**
- **Episode Ledger**: Every run can be indexed in local SQLite with structured episode, decision, reward, trace, experiment, critic, and memory-reference records
- **Deterministic Reward Store**: Fixed-horizon delayed rewards compare raw return and benchmark-adjusted alpha without using an LLM judge as the score source
- **Normalized Trace Spans**: Audit JSON is converted into joinable spans for prompts, LLM calls, tools, agent outputs, node events, and final decisions
- **Experiment Registry**: Config hash, prompt version, model provider, selected analysts, memory policy, critic version, reward version, and leakage risk are tracked for comparable evaluations
- **Critic and Memory Candidates**: Initial critic diagnostics produce failure tags and memory candidates, but do not auto-modify prompts or inject new memory into production decisions
- **Offline Export**: JSONL export prepares the data shape needed for later supervised learning, contextual bandits, or offline RL experiments

### 📊 **Data And Asset Coverage**
- **Equities First**: Core evaluation defaults benchmark stocks against SPY
- **Crypto Supported**: Crypto symbols such as `BTC/USD` and `ETH/USD` are supported for analysis, with BTC used as the default crypto benchmark where applicable
- **Multi-Asset Inputs**: Mixed symbol batches remain supported for research runs
- **Market Data Sources**: Alpaca remains the primary market data and optional execution adapter; yfinance is used by the evaluation resolver; Finnhub, FRED, CoinDesk/CryptoCompare, and DeFi Llama support specialized evidence collection

### 🌐 **Advanced Web Interface**
- **Multi-Symbol Dashboard**: Analyze multiple symbols simultaneously
- **Progress Tracking**: Real-time progress table showing analysis status for each symbol
- **Interactive Charts**: Live Alpaca data integration with technical indicators
- **Tabbed Reports**: Organized analysis reports with easy navigation
- **Chat-Style Debates**: Visualize agent debates as conversation threads
- **Optional Execution Panel**: View positions, recent orders, and trade actions when Alpaca execution is intentionally enabled
- **Model Configuration**: Choose provider, model, provider-specific parameters, output language, and checkpoint resume from the UI

## AlpacaTradingAgent Framework

AlpacaTradingAgent is a multi-agent market research framework that mirrors parts of an investment committee: evidence collection, adversarial debate, decision synthesis, and risk review. The system can still hand a structured final action to Alpaca, but the product emphasis is the quality and auditability of the decision process.

<p align="center">
  <img src="assets\schema.png" style="width: 100%; height: auto;">
</p>

> AlpacaTradingAgent is designed for research and educational purposes. Decision metrics may vary based on the selected models, prompts, horizon, data quality, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

The framework decomposes market research into specialized roles while preserving durable logs and structured evaluation artifacts.

## Evaluation Foundation

The project now includes a local evaluation subsystem under `tradingagents/eval/`.
It moves the system beyond a pure LLM workflow executor by making each decision
traceable, replayable, scoreable, and exportable. This is still **not** an
auto-learning or RL trading system: prompts are not rewritten automatically,
memory is not auto-promoted into production prompts, and model weights are not
trained.

By default, the ledger uses:

```text
~/.tradingagents/eval/agent_eval.sqlite
```

The main evaluation records are:

- `episodes`: run metadata, symbol, date, config, selected analysts, status, final signal, and audit path
- `decisions`: deterministic parsing of final and intermediate decision text into actions, confidence, horizon, thesis, invalidation, and risk fields
- `rewards`: delayed fixed-horizon reward status and reward components
- `trace_spans`: normalized references to audit events without duplicating full prompt or tool payloads
- `experiments`: config hash, prompt/model versions, selected analysts, memory policy, critic version, reward version, and leakage risk
- `critic_records`: diagnostic failure tags and improvement candidates tied to resolved rewards
- `memory_items`, `memory_links`, `memory_retrievals`, `memory_promotions`: governed memory observation scaffolding for future Memory V2 work

Useful commands:

```bash
# AI-agent navigation map and default debug path.
python -m cli.main agent-map --format json
python -m cli.main run-index --run-id <run_id> --format json
python -m cli.main quality-index --run-id <run_id> --format json
python -m cli.main retrieval-pack --type risk_review --run-id <run_id> --format json

# Collect historical low-leakage episodes. Live web/news tools are disabled by default.
python -m tradingagents.eval collect \
  --symbols AAPL,MSFT \
  --dates 2026-01-02,2026-01-03 \
  --config config.json

# Resolve rewards for episodes whose holding period has matured.
python -m tradingagents.eval score --as-of 2026-05-10

# Normalize audit JSON into trace spans.
python -m tradingagents.eval normalize-traces --since 2026-01-01

# Create deterministic critic diagnostics for resolved episodes.
python -m tradingagents.eval critique --due-only

# Compare results by experiment, horizon, and symbol.
python -m tradingagents.eval report \
  --since 2026-01-01 \
  --group-by experiment,horizon,symbol

# Export joinable offline data for later modeling.
python -m tradingagents.eval export \
  --format jsonl \
  --since 2026-01-01 \
  --output eval_export.jsonl
```

For debugging, prefer `run-index -> quality-index -> retrieval-pack -> raw audit
excerpt`. Raw audit JSON remains the source of truth, but it is intentionally
not the first surface for AI agents or routine developer inspection.

See [docs/evolution-roadmap.md](docs/evolution-roadmap.md) for the full roadmap
from evaluation foundation to Memory V2, critic pipelines, strategy libraries,
and later offline policy/RL layers.

### Enhanced Analyst Team (5 Agents)
- **Market Analyst**: Evaluates overall market conditions, sector trends, and market sentiment indicators
- **Social Sentiment Analyst**: Analyzes Reddit, OpenAI web-search sentiment, and public market narratives
- **News Analyst**: Monitors financial news, earnings announcements, and global events that impact markets
- **Fundamental Analyst**: Evaluates company financials, earnings reports, and intrinsic value calculations
- **Macro Analyst**: Analyzes Federal Reserve data, economic indicators, and macroeconomic trends using FRED API

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance opportunity, risk, evidence quality, and horizon fit across supported assets.

### Trader Agent
- Composes reports from analysts and researchers into a horizon-aware plan. The plan includes thesis, action, invalidation, risk budget, review cadence, and position logic. Optional Alpaca execution is downstream of this decision artifact.

### Risk Management and Portfolio Manager
- Reviews the trader plan from multiple risk postures and emits the final structured decision. Portfolio and Alpaca controls are available when execution is enabled, but the core responsibility is decision quality and risk reasoning.

## Installation and Setup

### Installation

Clone AlpacaTradingAgent:
```bash
git clone https://github.com/huygiatrng/AlpacaTradingAgent.git
cd AlpacaTradingAgent
```

Install dependencies:
```bash
pip install -r requirements.txt
```

### Required APIs Configuration

For research and evaluation runs, you mainly need an LLM provider and the data providers used by your selected analysts. Alpaca credentials are required only for Alpaca market-data paths and optional execution.

1. **Copy the sample environment file**:
   ```bash
   cp env.sample .env
   ```

2. **Edit the `.env` file** with your API keys:

#### Core APIs
- **LLM Provider Key**:
  - OpenAI is the default path, but Google, Anthropic, xAI, DeepSeek, Qwen, GLM, OpenRouter, Ollama, local OpenAI-compatible endpoints, and Azure OpenAI are supported
  - OpenAI web-search tools require `OPENAI_API_KEY`

- **Market and Research Data Keys**:
  - Finnhub supports equity news and company data
  - FRED supports macro analysis
  - CoinDesk/CryptoCompare and DeFi Llama support crypto-specific evidence when crypto analysts/tools are used

#### LLM Provider APIs
Set `LLM_PROVIDER` in `.env`, the CLI, or the WebUI. Supported providers include:
- **OpenAI**: `OPENAI_API_KEY`
- **Local OpenAI-compatible**: `OPENAI_USE_LOCAL=true`, `OPENAI_BASE_URL`, optional `OPENAI_API_KEY`
- **Google Gemini**: `GOOGLE_API_KEY`
- **Anthropic Claude**: `ANTHROPIC_API_KEY`
- **xAI Grok**: `XAI_API_KEY`
- **DeepSeek**: `DEEPSEEK_API_KEY`
- **Qwen/DashScope**: `DASHSCOPE_API_KEY`
- **GLM/Zhipu**: `ZHIPU_API_KEY`
- **OpenRouter**: `OPENROUTER_API_KEY`
- **Ollama**: no API key by default; configure the backend URL
- **Azure OpenAI**: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, `AZURE_OPENAI_API_VERSION`

#### Financial Data APIs
- **Finnhub API Key** (used for stock news and company data):
  - Sign up at [Finnhub](https://finnhub.io/register)

- **FRED API Key** (used for macro analysis):
  - Get your free key from [FRED](https://fred.stlouisfed.org/docs/api/api_key.html)

#### Crypto Data APIs
- **CoinDesk/CryptoCompare API Key** (used for crypto news when crypto analysis is selected):
  - Sign up at [CryptoCompare](https://www.cryptocompare.com/cryptopian/api-keys)

#### Optional Execution APIs
- **Alpaca API Keys**:
  - Required only for Alpaca market-data paths, account views, and optional order execution
  - Sign up at [Alpaca Markets](https://app.alpaca.markets/signup)
  - Set `ALPACA_USE_PAPER=True` for paper trading experiments
  - Set `ALPACA_USE_PAPER=False` only when intentionally testing live execution

#### Optional APIs
- **SEC EDGAR** (official structured fundamentals source):
  - No API key is required, but SEC fair-access guidance requires a descriptive User-Agent.
  - Set `SEC_EDGAR_USER_AGENT` to an app/contact string before long-running cron use.
  - Used by the fundamentals analyst for official `submissions` metadata and structured XBRL `companyfacts`; secondary sources should not override SEC filing facts.

- **Alpha Vantage API Key** (optional MCP fundamentals source):
  - Get from [Alpha Vantage](https://www.alphavantage.co/support/#api-key)
  - Used by the fundamentals analyst for company overview, financial statements, earnings, estimates, and insider transactions
  - Fallback routing is optional and does not replace Alpaca as the primary market data path

#### Runtime Paths
`env.sample` also documents optional runtime paths:
- `TRADINGAGENTS_RESULTS_DIR` for report output
- `TRADINGAGENTS_CACHE_DIR` for cache and checkpoint files
- `TRADINGAGENTS_MEMORY_LOG_PATH` for persistent decision memory
- `TRADINGAGENTS_EPISODE_LEDGER_PATH` for the evaluation SQLite ledger

3. **Restart the application** after setting up your API keys.

> **Note**: Without valid Alpaca API keys, research and evaluation workflows can still run when their selected data/LLM providers are configured. Alpaca-specific charts, positions, and execution will fall back or be unavailable.
> Trend-horizon Alpaca execution gating is enforced in the WebUI; the CLI remains analysis-only even when trend execution semantics are enabled for prompts and logging.

### CLI Usage

You can try out the CLI by running:
```bash
python -m cli.main
```

The CLI is analysis-first and supports multiple symbols:
- Single stock: `NVDA`
- Single crypto: `BTC/USD`
- Multiple mixed assets: `NVDA, ETH/USD, AAPL, BTC/USD`
- Provider/model selection, custom model IDs, checkpoint resume, trading horizon selection, and provider-specific settings are available from the CLI prompts.
- For `position` and `trend` horizons, the CLI can mark runs as execution-enabled for prompt/log semantics, but it still does not place Alpaca orders.

### Web UI Usage

Launch the enhanced Dash-based web interface:

```bash
python run_webui_dash.py --port 7860
```

If you open the app through a preview/proxy URL, start it with the same base
path so Dash serves its assets and callback endpoints under that prefix:

```bash
python run_webui_dash.py --port 7860 --base-path /proxy/7860/
```

Common options:
- `--port PORT`: Specify a custom port (default: 7860)
- `--base-path PATH`: Serve Dash under a URL prefix for preview/proxy access, for example `/proxy/7860/`
- `--share`: Create a public link to share with others
- `--server-name`: Specify the server name/IP to bind to (default: 127.0.0.1)
- `--debug`: Run in debug mode with more logging
- `--max-threads N`: Set the maximum number of threads (default: 40)

or launch it with Docker:

```bash
cp env.sample .env
# Edit .env with your provider, market data, and Alpaca credentials first.
docker compose up -d --build
```

This starts a local web server at http://localhost:7860. To use a different
host port, set `HOST_PORT`, for example `HOST_PORT=7861 docker compose up -d --build`.

### Prompt Customization

Model-facing prompts live in `tradingagents/prompts/templates`. Edit those
Markdown templates to tune analyst, researcher, trader, risk, signal extraction,
and reflection behavior from one place. Templates are grouped by role:
`analysts/`, `researchers/`, `managers/`, `trader/`, `risk/`, `trading_modes/`,
`graph/`, and `shared/`.

To keep custom prompts outside the repo, copy selected templates to another
folder and set `TRADINGAGENTS_PROMPT_DIR` to that path. Keep the same group path
for overrides, for example `analysts/market_system.md`. Missing files fall back
to the bundled templates.

## Research Workflow

The usual workflow is:

1. Select symbols, analysts, LLM provider, trading horizon, and runtime settings.
2. Run the multi-agent research graph.
3. Inspect analyst reports, debates, trader plan, and risk-manager final decision.
4. Let the Episode Ledger store the run metadata, structured decisions, audit path, trace spans, and experiment metadata.
5. After the holding period matures, run `python -m tradingagents.eval score`.
6. Use `report`, `critique`, and `export` to compare decision quality and prepare later memory/learning work.

This puts evaluation before automation. The project should accumulate high-quality decision data before enabling any self-improvement loop.

#### Enhanced Web UI Features

The web interface is now best understood as a research and review console, with optional trading controls:

**Multi-Asset Analysis Dashboard**
- Analyze multiple stocks and crypto assets simultaneously
- Real-time progress tracking for each symbol
- Support for mixed portfolios (e.g., `"NVDA, ETH/USD, AAPL"`)

<p align="center">
  <img src="assets/demo/config_and_run.gif" style="width: 100%; height: auto;">
</p>

**Optional Alpaca Integration**
- View current Alpaca positions and recent orders
- Execute trades directly from the interface only when intentionally enabled
- Liquidate positions when Alpaca controls are configured
- Real-time portfolio value tracking

<p align="center">
  <img src="assets/demo/analyst_list.gif" style="width: 100%; height: auto;">
</p>

**Interactive Charts & Data**
- Live price charts powered by Alpaca API
- Technical indicators and analysis overlays
- Support for both stock and crypto price data

**Enhanced Reporting Interface**
- Tabbed navigation for different analysis reports
- Chat-style conversation view for agent debates
- Progress table showing analysis status for each symbol
- Downloadable reports and trade recommendations

<p align="center">
  <img src="assets/demo/reports_and_final_result.gif" style="width: 100%; height: auto;">
</p>

**Optional Automation Controls**
- Schedule recurring analysis during market hours
- Configure auto-execution only for controlled paper/live execution experiments
- Set custom analysis intervals (every N hours)
- Keep execution disabled when the goal is research/evaluation only

**LLM and Runtime Controls**
- Select OpenAI, local OpenAI-compatible, Google, Anthropic, xAI, DeepSeek, Qwen, GLM, OpenRouter, Ollama, or Azure OpenAI
- Configure custom model IDs for compatible providers and Azure deployment names
- Tune GPT reasoning controls, Gemini thinking level, Claude effort, output language, and checkpoint resume

## AlpacaTradingAgent Package

### Implementation Details

Built with LangGraph for flexibility and modularity. The enhanced version integrates multiple LLM providers, market/research data tools, an audit logger, a local evaluation ledger, and optional Alpaca execution. We recommend `gpt-5.4-mini` for quick agents and `gpt-5.4` or stronger models for deeper manager/trader stages.

### Python Usage

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Initialize with default config
ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# Analyze a single stock
_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)

# Analyze multiple assets, including optional crypto symbols
symbols = ["NVDA", "ETH/USD", "AAPL"]
for symbol in symbols:
    _, decision = ta.propagate(symbol, "2024-05-10")
    print(f"{symbol}: {decision}")
```

### Custom Configuration

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Create custom config for enhanced features
config = DEFAULT_CONFIG.copy()
config["deep_think_llm"] = "gpt-5.4"  # Strong current default
config["quick_think_llm"] = "gpt-5.4-mini"  # Balanced current default
config["quick_llm_params"] = {
    "reasoning_effort": "low",
    "text_verbosity": "low",
    "reasoning_summary": "auto",
}
config["deep_llm_params"] = {
    "reasoning_effort": "medium",
    "text_verbosity": "medium",
    "reasoning_summary": "auto",
}
config["max_debate_rounds"] = 2  # Increase debate rounds
config["online_tools"] = True  # Use real-time data
config["allow_shorts"] = False  # Investment mode: BUY/HOLD/SELL
config["checkpoint_enabled"] = False  # Enable to resume failed graph runs
config["memory_log_path"] = "~/.tradingagents/memory/trading_memory.md"
config["episode_ledger_enabled"] = True
config["episode_ledger_path"] = "~/.tradingagents/eval/agent_eval.sqlite"
config["trading_horizon"] = "swing"  # swing, position, or trend
config["trend_execution_enabled"] = False  # position/trend are research-only unless explicitly enabled
config["news_global_openai_enabled"] = False  # Macro handles broad global context by default

# Parallel execution settings (to avoid API overload)
config["parallel_analysts"] = True  # Run analysts in parallel (default: True)
config["analyst_start_delay"] = 0.5  # Delay between starting each analyst (seconds)
config["analyst_call_delay"] = 0.1  # Delay before making analyst calls (seconds)
config["tool_result_delay"] = 0.2  # Delay between tool results and next call (seconds)

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# Analyze an optional crypto symbol
_, decision = ta.propagate("BTC/USD", "2024-05-10")
print(decision)
```

For non-OpenAI providers, switch the provider and model IDs:

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "google"
config["quick_think_llm"] = "gemini-2.5-flash"
config["deep_think_llm"] = "gemini-3.1-pro-preview"
config["google_thinking_level"] = "high"

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)
```

## Contributing

We welcome contributions from the community. AlpacaTradingAgent is an independent project that builds upon concepts from the original TradingAgents framework, with current emphasis on decision quality, evaluation infrastructure, memory systems, critic workflows, and research ergonomics.

## Acknowledgments

This project is inspired by and builds upon concepts from the original [TradingAgents](https://github.com/TauricResearch/TradingAgents) framework by Tauric Research. We extend our gratitude to the original authors for their pioneering work in multi-agent financial trading systems.

**AlpacaTradingAgent** is an independent project focused on auditable multi-agent market research, structured decision evaluation, and future memory/learning infrastructure. Alpaca connectivity remains an important adapter, but not the sole center of the architecture.

## Citation

Please reference the original TradingAgents work that inspired this project:

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```

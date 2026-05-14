import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER": "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM": "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM": "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL": "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE": "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS": "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED": "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER": "benchmark_ticker",
}


def _coerce_env_value(value: str, reference):
    """Coerce env-var strings to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* overrides in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.getenv(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce_env_value(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "eval_results"),
    "memory_log_path": os.getenv(
        "TRADINGAGENTS_MEMORY_LOG_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md"),
    ),
    "memory_log_max_entries": None,
    "episode_ledger_enabled": True,
    "episode_ledger_path": os.getenv(
        "TRADINGAGENTS_EPISODE_LEDGER_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "eval", "agent_eval.sqlite"),
    ),
    "eval_reward_version": "v1_directional_alpha",
    "eval_transaction_cost_bps": 10,
    "eval_neutral_band_bps": {"swing": 100, "position": 300, "trend": 500},
    "prompt_version": "default",
    "memory_policy": "legacy",
    "critic_version": "v1_diagnostic_tags",
    "checkpoint_enabled": False,
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS": "^NSEI",
        ".BO": "^BSESN",
        ".T": "^N225",
        ".HK": "^HSI",
        ".L": "^FTSE",
        ".TO": "^GSPTSE",
        ".AX": "^AXJO",
        "": "SPY",
    },
    # "data_dir": "/Users/yluo/Documents/Code/ScAI/FR1-data",
    "data_dir": "data/ScAI/FR1-data",
    "data_cache_dir": os.getenv(
        "TRADINGAGENTS_CACHE_DIR",
        os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
            "dataflows/data_cache",
        ),
    ),
    # LLM settings
    "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "backend_url": None,
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "output_language": "zh-CN",
    "deep_llm_params": {
        "reasoning_effort": "medium",
        "text_verbosity": "medium",
        "reasoning_summary": "auto",
        "max_output_tokens": None,
        "store": False,
        "parallel_tool_calls": True,
    },
    "quick_llm_params": {
        "reasoning_effort": "low",
        "text_verbosity": "low",
        "reasoning_summary": "auto",
        "max_output_tokens": None,
        "store": False,
        "parallel_tool_calls": True,
    },
    # Debate and discussion settings
    "max_debate_rounds": 4,
    "max_risk_discuss_rounds": 3,
    "max_recur_limit": 200,
    # Trading settings
    "allow_shorts": False,  # False = Investment mode (BUY/HOLD/SELL), True = Trading mode (LONG/NEUTRAL/SHORT)
    "trading_horizon": "swing",  # swing = 2-10 days, position = 1-3 months, trend = 3-6 months
    "trend_execution_enabled": False,  # Trend horizons are research-only unless explicitly enabled
    "horizon_profiles": {
        "swing": {
            "label": "Swing",
            "holding_period": "2-10 trading days",
            "primary_timeframes": "1h/4h/1d",
        },
        "position": {
            "label": "Position",
            "holding_period": "1-3 months",
            "primary_timeframes": "1d/1w",
        },
        "trend": {
            "label": "Trend",
            "holding_period": "3-6 months",
            "primary_timeframes": "1w/1mo",
        },
    },
    # Execution settings
    "parallel_analysts": True,  # True = Run analysts in parallel for faster execution, False = Sequential execution
    "parallel_risk_first_round": True,  # Run Risky/Safe/Neutral in parallel only for round 1, then revert to linear flow
    "analyst_start_delay": 0.5,  # Delay in seconds between starting each analyst (to avoid API overload)
    "risk_analyst_start_delay": 0.35,  # Delay between starting first-round risk analysts in parallel mode
    "analyst_call_delay": 0.1,  # Delay in seconds before making analyst calls
    "tool_result_delay": 0.2,  # Delay in seconds between tool results and next analyst call
    # Context management settings (avoid prompt overflows in downstream agents)
    "report_context_budget_tokens": 5500,  # Max retrieved evidence budget per downstream agent call
    "report_context_max_chunks": 16,  # Max retrieved chunks injected into any single downstream prompt
    "report_context_min_chunks_per_report": 1,  # Ensure each non-empty analyst report is represented
    "report_context_chunk_chars": 900,  # Chunk size used to index analyst reports
    "report_context_chunk_overlap": 120,  # Overlap between report chunks
    "report_context_max_points_per_report": 8,  # Coverage bullets kept per report
    "report_context_point_chars": 220,  # Max chars per coverage bullet
    "report_context_excerpt_chars": 420,  # Max chars per retrieved excerpt injected into prompts
    "report_context_memory_chars": 12000,  # Max chars for memory embedding context
    "report_context_compact_points_per_report": 3,  # Claims per report for compact downstream packet
    "report_context_compact_point_chars": 180,  # Max chars per compact claim
    "report_context_compact_excerpt_chars": 240,  # Max chars per compact evidence excerpt
    "report_context_compact_max_excerpts": 8,  # Max compact evidence excerpts injected per prompt
    "debate_digest_max_messages": 6,  # Max recent debate messages included in compact debate digest
    "debate_digest_message_chars": 520,  # Max chars per message in debate digest
    "debate_digest_total_chars": 2600,  # Total max chars for debate digest block
    "include_full_reports_in_prompts": False,  # If True, inject full raw analyst reports into downstream prompts (very slow)
    "max_tool_iterations_per_agent": 8,  # Max tool-call loop turns per analyst node
    "max_same_tool_call_repeats": 1,  # Max repeats for the same tool+args signature in a single analyst node
    # Tool settings
    "online_tools": True,
    "tool_semantic_retry_enabled": True,  # Retry web-search tool calls once on low-quality interactive/undersized output
    "tool_semantic_retry_max_retries": 1,
    "tool_semantic_retry_backoff_seconds": 0.8,
    "tool_semantic_retry_disabled_tools": [
        "get_global_news_openai",
        "get_macro_news_openai",
    ],
    "data_fallback_enabled": False,  # Optional yfinance backup for supported Alpaca data failures
    "web_search_timeout_extension_seconds": 45,  # Extra timeout buffer added by timing wrapper for web-search tools
    "sellthenews_enabled": True,
    "sellthenews_base_url": "https://mcp.sellthenews.org/mcp",
    "sellthenews_timeout_seconds": 8,
    "sellthenews_news_enabled": True,
    "sellthenews_social_enabled": True,
    "sellthenews_macro_enabled": True,
    "sellthenews_options_enabled": False,
    "sellthenews_options_chain_api_enabled": True,
    "sellthenews_options_greeks": "gamma",
    "sellthenews_options_default_expiration": None,
    "sellthenews_options_max_chars": 4500,
    "sellthenews_options_spot_mismatch_threshold_pct": 5.0,
    "sellthenews_fallback_on_sparse": True,
    "alpha_vantage_mcp_enabled": True,
    "alpha_vantage_mcp_base_url": "https://mcp.alphavantage.co/mcp",
    "alpha_vantage_mcp_timeout_seconds": 8,
    "alpha_vantage_fundamentals_enabled": True,
    "alpha_vantage_fallback_on_sparse": True,
    "news_global_openai_enabled": False,  # News analyst uses fast ticker sources by default; macro handles broad global context
    "global_news_fast_profile": True,  # Keep global-news tool lean even at medium/deep research depth
    "stock_news_fast_profile": True,  # Keep stock-news web-search tool lean at medium/deep depth
    "fundamentals_fast_profile": True,  # Keep fundamentals web-search tool lean at medium/deep depth
    "global_news_timeout_seconds": 150,  # Timeout for get_global_news_openai web-search calls
    "global_news_max_output_tokens": 1200,  # Applied to models that support explicit output-token caps
    "global_news_max_events": 8,  # Cap number of events requested from global-news tool
    "global_news_word_budget": 550,  # Target output length from global-news tool
    "stock_news_timeout_seconds": 120,  # Timeout for get_stock_news_openai web-search calls
    "stock_news_max_output_tokens": 900,  # Output-token cap for social/news web-search summary tool
    "social_openai_stock_news_enabled": True,  # Available as a low-priority backstop after SellTheNews/grounded sources
    "grounded_social_evidence_enabled": True,  # Prefetch public StockTwits/Reddit samples for social analyst grounding
    "grounded_social_timeout_seconds": 6,
    "stocktwits_message_limit": 12,
    "reddit_public_limit_per_subreddit": 3,
    "fundamentals_timeout_seconds": 120,  # Timeout for get_fundamentals_openai web-search calls
    "fundamentals_max_output_tokens": 1000,  # Output-token cap for fundamentals web-search summary tool
    "fundamentals_include_reasoning": False,  # Keep web-search fundamentals latency bounded by default
    "google_news_max_pages": 3,  # Google News pages fetched before dedupe/limit
    "google_news_max_items": 18,  # Max deduped Google News items returned to analysts
    "finnhub_news_max_items": 24,  # Max Finnhub company-news items returned to analysts
    "finnhub_news_max_chars": 12000,  # Max Finnhub company-news payload size
    "openai_store_responses": False,  # Disable response storing by default to reduce latency/payload
    # API keys (these will be overridden by environment variables if present)
    "openai_api_key": None,
    "openai_use_local": False,  # Route core LLM calls to a local OpenAI-compatible endpoint
    "openai_base_url": None,  # Example: http://localhost:1234/v1
    "embedding_provider": os.getenv("TRADINGAGENTS_EMBEDDING_PROVIDER", "openai"),
    "openai_embedding_model": "text-embedding-ada-002",
    "google_embedding_model": os.getenv("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
    "finnhub_api_key": None,
    "alpaca_api_key": None,
    "alpaca_secret_key": None,
    "alpaca_use_paper": "True",  # Set to "True" to use paper trading, "False" for live trading
    "coindesk_api_key": None,
})

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
    "trade_lifecycle_db_path": os.getenv(
        "TRADINGAGENTS_TRADE_LIFECYCLE_DB_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "trade_lifecycle", "trade_lifecycle.sqlite"),
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
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.5",
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
    "trading_horizon": "position",  # swing = 2-10 days, position = 1-3 months, trend = 3-6 months
    "trend_execution_enabled": False,  # Trend horizons are research-only unless explicitly enabled
    "portfolio_style": os.getenv("TRADINGAGENTS_PORTFOLIO_STYLE", "trend_concentrated"),
    "target_ticket_count": int(os.getenv("TRADINGAGENTS_TARGET_TICKET_COUNT", "5")),
    "theme_concentration_enabled": True,
    "max_single_name_notional_pct": 0.30,
    "max_theme_notional_pct": 0.70,
    "max_single_name_risk_pct": 0.025,
    "max_theme_risk_pct": 0.08,
    "max_account_open_risk_pct": 0.12,
    "leader_notional_range_pct": [0.20, 0.30],
    "core_notional_range_pct": [0.10, 0.20],
    "starter_notional_range_pct": [0.05, 0.10],
    "decision_policy_enabled": True,
    "horizon_factor_weights": {
        "swing": {
            "technical": 0.55,
            "news_social_catalyst": 0.20,
            "macro": 0.10,
            "fundamentals_valuation": 0.10,
            "portfolio_risk": 0.05,
        },
        "position": {
            "trend_relative_strength": 0.35,
            "catalyst_news_social": 0.25,
            "fundamentals": 0.15,
            "macro_liquidity": 0.15,
            "valuation": 0.10,
        },
        "trend": {
            "valuation": 0.30,
            "fundamentals": 0.25,
            "trend_regime": 0.20,
            "macro_liquidity": 0.15,
            "sentiment_news": 0.10,
        },
    },
    "horizon_gate_thresholds": {
        "swing": {"min_weighted_score": 0.58, "min_technical_score": 0.50},
        "position": {"min_weighted_score": 0.60, "min_trend_confirmations": 2},
        "trend": {"min_weighted_score": 0.62, "max_valuation_score_without_support": 0.35},
    },
    "risk_budget_ladder": {
        "blocked": 0.0,
        "weak_min": 0.005,
        "weak_max": 0.010,
        "valid_starter_min": 0.010,
        "valid_starter_max": 0.015,
        "confirmed_leader_min": 0.015,
        "confirmed_leader_max": 0.025,
    },
    "minimum_executable_notional_pct": 0.02,
    "decision_policy_dynamic_soft_gates_enabled": True,
    "soft_gate_multipliers": {
        "weighted_score": 0.75,
        "technical": 0.65,
        "trend_theme": 0.70,
        "valuation_fundamentals": 0.70,
    },
    "minimum_soft_gate_multiplier": 0.25,
    "trade_lifecycle_default_notional": float(os.getenv("TRADINGAGENTS_TRADE_LIFECYCLE_DEFAULT_NOTIONAL", "1000")),
    "trade_lifecycle_max_gap_pct": float(os.getenv("TRADINGAGENTS_TRADE_LIFECYCLE_MAX_GAP_PCT", "0.08")),
    "trade_lifecycle_min_volume_ratio": None,
    "trade_lifecycle_max_notional_pct": None,
    "trade_lifecycle_debounce_observations": 1,
    "trade_lifecycle_hysteresis_pct": 0.0,
    "trade_lifecycle_valid_days": None,
    "trade_monitor_respect_market_hours": os.getenv("TRADINGAGENTS_TRADE_MONITOR_RESPECT_MARKET_HOURS", "true").lower()
    in ("1", "true", "yes", "on"),
    "trade_monitor_use_alpaca_clock": os.getenv("TRADINGAGENTS_TRADE_MONITOR_USE_ALPACA_CLOCK", "true").lower()
    in ("1", "true", "yes", "on"),
    "trade_monitor_heartbeat_stale_seconds": int(os.getenv("TRADINGAGENTS_TRADE_MONITOR_HEARTBEAT_STALE_SECONDS", "600")),
    "trade_monitor_review_webhook_url": os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_WEBHOOK_URL", ""),
    "trade_monitor_webhook_timeout_seconds": float(os.getenv("TRADINGAGENTS_TRADE_MONITOR_WEBHOOK_TIMEOUT_SECONDS", "5")),
    "trade_monitor_review_im_channel": os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_CHANNEL", ""),
    "trade_monitor_review_im_account": os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_ACCOUNT", ""),
    "trade_monitor_review_im_target": os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_TARGET", ""),
    "trade_monitor_openclaw_bin": os.getenv("TRADINGAGENTS_TRADE_MONITOR_OPENCLAW_BIN", "openclaw"),
    "trade_monitor_openclaw_timeout_seconds": float(
        os.getenv("TRADINGAGENTS_TRADE_MONITOR_OPENCLAW_TIMEOUT_SECONDS", "10")
    ),
    "crowding_gate_enabled": True,
    "momentum_crash_gate_enabled": True,
    "crowding_thresholds": {
        "price_vs_50d_high": 0.20,
        "price_vs_200d_high": 0.45,
        "drawdown_52w_tight": -0.05,
        "return_6m_high": 0.50,
        "volume_attention_ratio": 2.0,
        "bullish_social_ratio": 0.70,
        "mention_zscore": 2.0,
        "call_put_oi_ratio": 2.5,
        "iv_percentile": 80.0,
        "same_theme_notional": 0.60,
        "same_theme_risk": 0.07,
    },
    "momentum_crash_thresholds": {
        "benchmark_63d_return": -0.10,
        "benchmark_126d_return": -0.15,
        "benchmark_drawdown": -0.12,
        "benchmark_realized_vol_21d_percentile": 80.0,
        "benchmark_5d_rebound": 0.04,
        "benchmark_21d_rebound": 0.08,
        "high_momentum_relative_strength": 0.15,
        "high_momentum_6m_return": 0.40,
    },
    "risk_overlay_multipliers": {
        "low": 1.0,
        "medium": 0.75,
        "high": 0.50,
        "extreme": 0.25,
        "momentum_crash": 0.50,
    },
    "crowding_extreme_blocks": False,
    "momentum_crash_blocks": False,
    "theme_map": {
        "BE": "ai_power_infrastructure",
        "VRT": "ai_power_infrastructure",
        "ETN": "ai_power_infrastructure",
        "PWR": "ai_power_infrastructure",
        "CEG": "ai_power_infrastructure",
        "GEV": "ai_power_infrastructure",
        "NVDA": "ai_semiconductors",
        "AMD": "ai_semiconductors",
        "AVGO": "ai_semiconductors",
        "ARM": "ai_semiconductor_ip",
        "TSM": "ai_semiconductors",
        "MU": "ai_memory",
        "ORCL": "ai_infrastructure_software",
    },
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
    "point_in_time_source_policy": os.getenv("TRADINGAGENTS_POINT_IN_TIME_SOURCE_POLICY", "auto"),
    "tool_semantic_retry_enabled": True,  # Retry web-search tool calls once on low-quality interactive/undersized output
    "tool_semantic_retry_max_retries": 1,
    "tool_semantic_retry_backoff_seconds": 0.8,
    "tool_semantic_retry_disabled_tools": [
        "get_global_news_openai",
        "get_macro_news_openai",
    ],
    "data_quality_enabled": True,
    "data_quality_header_enabled": True,
    "data_quality_soft_gate_enabled": True,
    "data_quality_cross_check_enabled": True,
    "data_quality_raw_retention": "full",
    "data_fallback_enabled": False,  # Optional yfinance backup for supported Alpaca data failures
    "web_search_timeout_extension_seconds": 45,  # Extra timeout buffer added by timing wrapper for web-search tools
    "alpha_discovery_db_path": os.getenv(
        "TRADINGAGENTS_ALPHA_DISCOVERY_DB_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "alpha_discovery", "alpha_discovery.sqlite"),
    ),
    "alpha_discovery_wsb_top_sectors": 10,
    "alpha_discovery_wsb_per_sector": 1,
    "alpha_discovery_dd_list_limit": 20,
    "alpha_discovery_full_ata_cooldown_hours": 24,
    "alpha_discovery_max_full_ata_runs_per_day": 5,
    "alpha_discovery_default_ata_daily_budget": 5,
    "alpha_discovery_auto_run_a_list": os.getenv(
        "TRADINGAGENTS_ALPHA_DISCOVERY_AUTO_RUN_A_LIST",
        "true",
    ).strip().lower()
    in {"1", "true", "yes", "on"},
    "alpha_discovery_ata_horizon": os.getenv("TRADINGAGENTS_ALPHA_DISCOVERY_ATA_HORIZON", "position"),
    "alpha_discovery_ata_trading_mode": os.getenv("TRADINGAGENTS_ALPHA_DISCOVERY_ATA_TRADING_MODE", "investment"),
    "alpha_discovery_ata_analysts": os.getenv(
        "TRADINGAGENTS_ALPHA_DISCOVERY_ATA_ANALYSTS",
        "market,fundamentals,news,social,macro",
    ),
    "alpha_discovery_confirmation_enabled": True,
    "alpha_discovery_news_confirmation_enabled": True,
    "alpha_discovery_search_news_confirmation_enabled": False,
    "alpha_discovery_live_news_confirmation_enabled": False,
    "alpha_discovery_policy_social_confirmation_enabled": False,
    "alpha_discovery_news_confirmation_max_age_days": int(
        os.getenv("TRADINGAGENTS_ALPHA_DISCOVERY_NEWS_CONFIRMATION_MAX_AGE_DAYS", "14")
    ),
    "alpha_discovery_require_news_confirmation_date": os.getenv(
        "TRADINGAGENTS_ALPHA_DISCOVERY_REQUIRE_NEWS_CONFIRMATION_DATE",
        "true",
    ).strip().lower()
    in {"1", "true", "yes", "on"},
    "alpha_discovery_options_confirmation_enabled": False,
    "alpha_discovery_price_volume_confirmation_enabled": False,
    "alpha_discovery_price_volume_max_bar_age_days": int(
        os.getenv("TRADINGAGENTS_ALPHA_DISCOVERY_PRICE_VOLUME_MAX_BAR_AGE_DAYS", "5")
    ),
    "alpha_discovery_min_confirmations_for_a": 1,
    "alpha_discovery_min_confirmations_for_dd_a": 2,
    "alpha_discovery_soft_fail_collectors": True,
    "alpha_discovery_research_boost_enabled": os.getenv("TRADINGAGENTS_ALPHA_DISCOVERY_RESEARCH_BOOST_ENABLED", "true"),
    "alpha_discovery_research_boost_max": float(os.getenv("TRADINGAGENTS_ALPHA_DISCOVERY_RESEARCH_BOOST_MAX", "0.24")),
    "alpha_discovery_research_single_article_a_gate": os.getenv(
        "TRADINGAGENTS_ALPHA_DISCOVERY_RESEARCH_SINGLE_ARTICLE_A_GATE",
        "true",
    ),
    "alpha_discovery_research_source_quality_json": os.getenv(
        "TRADINGAGENTS_ALPHA_DISCOVERY_RESEARCH_SOURCE_QUALITY_JSON",
        "{}",
    ),
    "sellthenews_enabled": True,
    "sellthenews_base_url": "https://mcp.sellthenews.org/mcp",
    "sellthenews_timeout_seconds": 8,
    "sellthenews_news_enabled": True,
    "sellthenews_social_enabled": True,
    "sellthenews_macro_enabled": True,
    "sellthenews_dd_enabled": True,
    "sellthenews_dd_max_posts": 3,
    "sellthenews_dd_min_score": 0,
    "sellthenews_dd_min_comments": 0,
    "sellthenews_dd_max_chars": 6500,
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
    "finnhub_fundamentals_metric_stale_days": int(
        os.getenv("TRADINGAGENTS_FINNHUB_FUNDAMENTALS_METRIC_STALE_DAYS", "540")
    ),
    "sec_edgar_enabled": True,
    "sec_edgar_user_agent": os.getenv(
        "SEC_EDGAR_USER_AGENT",
        "AlpacaTradingAgent SEC-EDGAR research contact@example.com",
    ),
    "sec_edgar_cache_ttl_hours": 24,
    "sec_edgar_mapping_cache_ttl_days": 7,
    "sec_edgar_timeout_seconds": 12,
    "sec_edgar_max_quarters": 8,
    "sec_edgar_metric_stale_days": int(os.getenv("TRADINGAGENTS_SEC_EDGAR_METRIC_STALE_DAYS", "540")),
    "alpha_discovery_sec_confirmation_enabled": False,
    "news_global_openai_enabled": False,  # News analyst uses fast ticker sources by default; macro handles broad global context
    "global_news_fast_profile": True,  # Keep global-news tool lean even at medium/deep research depth
    "stock_news_fast_profile": True,  # Keep stock-news web-search tool lean at medium/deep depth
    "fundamentals_fast_profile": True,  # Keep fundamentals web-search tool lean at medium/deep depth
    "openai_sources_policy": os.getenv("TRADINGAGENTS_OPENAI_SOURCES_POLICY", "fallback"),
    "openai_source_call_budget_per_run": int(os.getenv("TRADINGAGENTS_OPENAI_SOURCE_CALL_BUDGET_PER_RUN", "1")),
    "openai_source_timeout_seconds": int(os.getenv("TRADINGAGENTS_OPENAI_SOURCE_TIMEOUT_SECONDS", "25")),
    "skip_openai_when_non_openai_sufficient": os.getenv(
        "TRADINGAGENTS_SKIP_OPENAI_WHEN_NON_OPENAI_SUFFICIENT",
        "true",
    ).strip().lower()
    in {"1", "true", "yes", "on"},
    "non_openai_sufficiency_min_chars": int(os.getenv("TRADINGAGENTS_NON_OPENAI_SUFFICIENCY_MIN_CHARS", "1200")),
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

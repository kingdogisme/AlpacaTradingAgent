"""
Control and configuration callbacks for TradingAgents WebUI
"""

from dash import ALL, Input, Output, State, ctx, html, no_update
import dash_bootstrap_components as dbc
import dash
import threading
import time

from webui.utils.state import app_state
from webui.utils.report_recovery import load_latest_run_reports
from webui.components.analysis import start_analysis
from tradingagents.dataflows.alpaca_utils import AlpacaUtils
from tradingagents.openai_model_registry import (
    get_default_model_for_provider,
    get_model_options_for_provider,
    get_provider_ui_metadata,
    get_ui_control_state,
    normalize_model_params,
    resolve_model_choice,
)


def _symbols_from_store(store_data):
    if not isinstance(store_data, dict):
        return []
    return _parse_symbol_text(store_data.get("symbols") or [])


def _build_analysis_store_data(
    symbols,
    mode_text,
    interval_text,
    horizon,
    trend_execution_enabled,
    status,
    message=None,
):
    return {
        "analysis_started": True,
        "analysis_status": status,
        "timestamp": time.time(),
        "symbols": symbols,
        "num_symbols": len(symbols),
        "mode": mode_text,
        "trading_horizon": horizon,
        "trend_execution_enabled": bool(trend_execution_enabled),
        "interval_text": interval_text,
        "message": message or "",
    }


def _state_reports_for_store(symbol):
    state = app_state.get_state(symbol) or {}
    return {
        report_type: content
        for report_type, content in (state.get("current_reports") or {}).items()
        if content
    }


def _reports_from_latest_runs(symbols):
    recovered_by_symbol = {}
    for symbol in symbols:
        recovered = load_latest_run_reports(symbol)
        if recovered and recovered.get("reports"):
            recovered_by_symbol[symbol] = recovered
    return recovered_by_symbol


def _build_restored_symbol_state(symbol, stored_reports):
    app_state.build_symbol_state_from_reports(
        symbol,
        stored_reports or {},
        complete=bool((stored_reports or {}).get("final_trade_decision")),
    )


def _restore_symbol_from_latest_run(symbol):
    recovered = load_latest_run_reports(symbol)
    if not recovered:
        app_state.init_symbol_state(symbol)
        return False
    state = app_state.build_symbol_state_from_reports(
        symbol,
        recovered.get("reports") or {},
        complete=recovered.get("status") == "completed",
        prompts=recovered.get("prompts") or {},
    )
    if recovered.get("trade_date"):
        state["trade_date"] = recovered["trade_date"]
    if recovered.get("final_signal"):
        state["recommended_action"] = recovered["final_signal"]
        if state.get("analysis_results"):
            state["analysis_results"]["decision"] = recovered["final_signal"]
    if recovered.get("run_file"):
        state["restored_from_run_file"] = recovered["run_file"]
    print(f"[RESTORE] Restored {symbol} reports from {recovered.get('run_file')}")
    return True


def _llm_group_style(enabled):
    return {} if enabled else {"display": "none"}


def _select_options(values):
    return [{"label": value, "value": value} for value in values]


def _normalize_symbol(value):
    symbol = str(value or "").strip().upper().strip(",;")
    return "".join(symbol.split())


def _parse_symbol_text(value):
    if isinstance(value, list):
        raw_symbols = value
    else:
        raw_symbols = str(value or "").replace(";", ",").split(",")

    symbols = []
    seen = set()
    for raw_symbol in raw_symbols:
        symbol = _normalize_symbol(raw_symbol)
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    return symbols


def _format_symbol_text(symbols):
    return ", ".join(_parse_symbol_text(symbols))


def _asset_detail(asset):
    details = [
        asset.get("name"),
        asset.get("asset_type"),
        asset.get("exchange"),
    ]
    return " · ".join(str(detail) for detail in details if detail)


def _symbol_suggestion_button(symbol, detail, icon="fa-magnifying-glass"):
    return html.Button(
        [
            html.I(className=f"fa-solid {icon} symbol-suggestion-icon"),
            html.Span(symbol, className="symbol-option-symbol"),
            html.Span(detail, className="symbol-option-detail"),
        ],
        id={"type": "symbol-suggestion-option", "symbol": symbol},
        type="button",
        className="symbol-suggestion-option",
    )


def _symbol_chip(symbol):
    return html.Span(
        [
            html.Span(symbol, className="symbol-chip-label"),
            html.Button(
                html.I(className="fa-solid fa-xmark"),
                id={"type": "symbol-chip-remove", "symbol": symbol},
                type="button",
                title=f"Remove {symbol}",
                className="symbol-chip-remove",
            ),
        ],
        className="symbol-chip",
    )


def _custom_model_group_style(provider, model):
    metadata = get_provider_ui_metadata(provider)
    return {} if metadata.get("custom_models") and model == "custom" else {"display": "none"}


def _custom_model_placeholder(provider, role):
    provider_key = (provider or "openai").lower()
    examples = {
        "local_openai": "qwen3:latest",
        "deepseek": "deepseek-v4-flash" if role == "quick" else "deepseek-v4-pro",
        "qwen": "qwen-plus",
        "glm": "glm-5",
        "openrouter": "openai/gpt-5.4-mini",
        "ollama": "qwen3:latest",
        "azure": f"{role}-deployment-name",
    }
    return examples.get(provider_key, "provider/model-name")


def _resolve_runtime_model(role, selected_model, custom_model):
    resolved = resolve_model_choice(selected_model, custom_model)
    if resolved:
        return resolved, None
    return None, f"Please enter a {role} custom model ID."


def _status_panel(title, body="", items=None, tone="neutral", icon="fa-circle-info"):
    copy_children = [html.Div(title, className="config-info-title")]
    if body:
        copy_children.append(html.Div(body, className="config-info-body"))

    content = [
        html.Div(
            [
                html.I(className=f"fa-solid {icon} config-info-icon"),
                html.Div(copy_children, className="config-info-copy"),
            ],
            className="config-info-heading",
        )
    ]
    if items:
        content.append(
            html.Div(
                [html.Span(item, className="config-info-pill") for item in items],
                className="config-info-pills",
            )
        )
    return html.Div(content, className=f"config-info-panel {tone}")


def _collect_llm_params(
    model,
    role,
    reasoning_effort,
    verbosity,
    summary,
    temperature,
    top_p,
    max_output_tokens,
    store,
    parallel_tool_calls,
):
    return normalize_model_params(
        model,
        {
            "reasoning_effort": reasoning_effort,
            "text_verbosity": verbosity,
            "reasoning_summary": summary,
            "temperature": temperature,
            "top_p": top_p,
            "max_output_tokens": max_output_tokens,
            "store": store,
            "parallel_tool_calls": parallel_tool_calls,
        },
        role=role,
    )


def register_control_callbacks(app):
    """Register all control and configuration callbacks"""

    def register_llm_param_callback(role):
        prefix = f"{role}-llm"

        @app.callback(
            [
                Output(f"{prefix}-info", "children"),
                Output(f"{prefix}-reasoning-effort-group", "style"),
                Output(f"{prefix}-reasoning-effort", "options"),
                Output(f"{prefix}-reasoning-effort", "value"),
                Output(f"{prefix}-verbosity-group", "style"),
                Output(f"{prefix}-verbosity", "options"),
                Output(f"{prefix}-verbosity", "value"),
                Output(f"{prefix}-summary-group", "style"),
                Output(f"{prefix}-summary", "options"),
                Output(f"{prefix}-summary", "value"),
                Output(f"{prefix}-temperature-group", "style"),
                Output(f"{prefix}-temperature", "value"),
                Output(f"{prefix}-top-p-group", "style"),
                Output(f"{prefix}-top-p", "value"),
                Output(f"{prefix}-max-output-group", "style"),
                Output(f"{prefix}-max-output-tokens", "value"),
                Output(f"{prefix}-store-group", "style"),
                Output(f"{prefix}-store", "value"),
                Output(f"{prefix}-parallel-tool-calls-group", "style"),
                Output(f"{prefix}-parallel-tool-calls", "value"),
                Output(f"{prefix}-params-accordion", "style"),
            ],
            [
                Input(f"{role}-llm", "value"),
                Input(f"{role}-llm-custom-model", "value"),
                Input("llm-provider", "value"),
            ],
        )
        def update_llm_param_controls(model, custom_model, provider):
            effective_model = resolve_model_choice(model, custom_model) or model
            state = get_ui_control_state(effective_model, role, provider)
            spec = state["spec"]
            defaults = state["defaults"]
            info = html.Div(
                [
                    html.Div(spec.get("label", model), className="llm-model-name"),
                    html.Div(spec.get("description", ""), className="llm-model-description"),
                    html.Span(state.get("price_hint", "standard"), className="llm-price-pill"),
                ],
                className="llm-model-summary",
            )

            reasoning_options = _select_options(spec.get("reasoning_effort_options", []))
            verbosity_options = _select_options(spec.get("text_verbosity_options", []))
            summary_options = _select_options(spec.get("reasoning_summary_options", []))
            has_advanced_params = any(
                spec.get(key)
                for key in (
                    "supports_reasoning_effort",
                    "supports_text_verbosity",
                    "supports_reasoning_summary",
                    "supports_temperature",
                    "supports_top_p",
                    "supports_max_output_tokens",
                    "supports_store",
                    "supports_parallel_tool_calls",
                )
            )

            return (
                info,
                _llm_group_style(spec.get("supports_reasoning_effort")),
                reasoning_options,
                defaults.get("reasoning_effort"),
                _llm_group_style(spec.get("supports_text_verbosity")),
                verbosity_options,
                defaults.get("text_verbosity"),
                _llm_group_style(spec.get("supports_reasoning_summary")),
                summary_options,
                defaults.get("reasoning_summary"),
                _llm_group_style(spec.get("supports_temperature")),
                defaults.get("temperature"),
                _llm_group_style(spec.get("supports_top_p")),
                defaults.get("top_p"),
                _llm_group_style(spec.get("supports_max_output_tokens")),
                defaults.get("max_output_tokens"),
                _llm_group_style(spec.get("supports_store")),
                defaults.get("store", False),
                _llm_group_style(spec.get("supports_parallel_tool_calls")),
                defaults.get("parallel_tool_calls", True),
                ({} if has_advanced_params else {"display": "none"}),
            )

    register_llm_param_callback("quick")
    register_llm_param_callback("deep")

    @app.callback(
        [
            Output("quick-llm", "options"),
            Output("quick-llm", "value"),
            Output("deep-llm", "options"),
            Output("deep-llm", "value"),
            Output("backend-url-group", "style"),
            Output("backend-url", "placeholder"),
            Output("llm-provider-info", "children"),
            Output("google-thinking-level-group", "style"),
            Output("anthropic-effort-group", "style"),
        ],
        [Input("llm-provider", "value")],
        [State("quick-llm", "value"), State("deep-llm", "value")],
    )
    def update_provider_models(provider, current_quick, current_deep):
        provider = provider or "openai"
        metadata = get_provider_ui_metadata(provider)
        quick_options = get_model_options_for_provider(provider, "quick")
        deep_options = get_model_options_for_provider(provider, "deep")
        quick_values = {option["value"] for option in quick_options}
        deep_values = {option["value"] for option in deep_options}
        quick_value = current_quick if current_quick in quick_values else get_default_model_for_provider(provider, "quick")
        deep_value = current_deep if current_deep in deep_values else get_default_model_for_provider(provider, "deep")
        provider_info = _status_panel(
            metadata["title"],
            f"{metadata['summary']} API key: {metadata['api_key']}. Endpoint: {metadata['endpoint']}.",
            metadata.get("pills"),
            tone="info",
            icon="fa-plug-circle-bolt",
        )
        backend_style = {} if metadata.get("backend_visible") else {"display": "none"}
        google_style = {} if provider == "google" else {"display": "none"}
        anthropic_style = {} if provider == "anthropic" else {"display": "none"}
        return (
            quick_options,
            quick_value,
            deep_options,
            deep_value,
            backend_style,
            metadata.get("endpoint_placeholder", "Optional provider endpoint"),
            provider_info,
            google_style,
            anthropic_style,
        )

    @app.callback(
        [
            Output("quick-llm-custom-model-group", "style"),
            Output("quick-llm-custom-model", "placeholder"),
            Output("deep-llm-custom-model-group", "style"),
            Output("deep-llm-custom-model", "placeholder"),
        ],
        [
            Input("llm-provider", "value"),
            Input("quick-llm", "value"),
            Input("deep-llm", "value"),
        ],
    )
    def update_custom_model_fields(provider, quick_model, deep_model):
        return (
            _custom_model_group_style(provider, quick_model),
            _custom_model_placeholder(provider, "quick"),
            _custom_model_group_style(provider, deep_model),
            _custom_model_placeholder(provider, "deep"),
        )

    @app.callback(
        Output("symbol-selected-chips", "children"),
        [Input("ticker-input", "value")],
    )
    def render_selected_symbol_chips(symbol_text):
        """Render selected symbols as removable chips."""
        selected_symbols = _parse_symbol_text(symbol_text)
        if not selected_symbols:
            return ""
        return [_symbol_chip(symbol) for symbol in selected_symbols]

    @app.callback(
        Output("symbol-suggestions", "children"),
        [
            Input("symbol-query-input", "value"),
            Input("ticker-input", "value"),
        ],
    )
    def update_symbol_suggestions(query, symbol_text):
        """Show a separate suggestion menu so typing never rebuilds the input itself."""
        query_symbol = _normalize_symbol(query)
        if not query_symbol:
            return ""

        selected_symbols = set(_parse_symbol_text(symbol_text))
        suggestions = []
        seen = set()

        try:
            assets = AlpacaUtils.search_assets(query_symbol, limit=8)
        except Exception as exc:
            print(f"Symbol search failed for {query_symbol}: {exc}")
            assets = []

        for asset in assets:
            symbol = _normalize_symbol(asset.get("symbol"))
            if not symbol or symbol in selected_symbols or symbol in seen:
                continue
            suggestions.append(_symbol_suggestion_button(symbol, _asset_detail(asset), icon="fa-chart-line"))
            seen.add(symbol)

        if query_symbol not in selected_symbols and query_symbol not in seen:
            suggestions.append(_symbol_suggestion_button(query_symbol, "Add custom symbol", icon="fa-plus"))

        if not suggestions:
            return html.Div("Already selected", className="symbol-suggestion-empty")

        return suggestions

    @app.callback(
        [
            Output("ticker-input", "value"),
            Output("symbol-query-input", "value"),
        ],
        [
            Input("symbol-query-input", "n_submit"),
            Input({"type": "symbol-suggestion-option", "symbol": ALL}, "n_clicks"),
            Input({"type": "symbol-chip-remove", "symbol": ALL}, "n_clicks"),
        ],
        [
            State("symbol-query-input", "value"),
            State("ticker-input", "value"),
        ],
        prevent_initial_call=True,
    )
    def update_selected_symbols(query_submits, suggestion_clicks, remove_clicks, query, symbol_text):
        """Add symbols from Enter or suggestion clicks, and remove chips."""
        selected_symbols = _parse_symbol_text(symbol_text)
        triggered_id = ctx.triggered_id
        triggered_value = ctx.triggered[0].get("value") if ctx.triggered else None
        if not triggered_value:
            return no_update, no_update

        if isinstance(triggered_id, dict):
            trigger_type = triggered_id.get("type")
            trigger_symbol = _normalize_symbol(triggered_id.get("symbol"))
            if trigger_type == "symbol-chip-remove" and trigger_symbol:
                updated_symbols = [symbol for symbol in selected_symbols if symbol != trigger_symbol]
                return _format_symbol_text(updated_symbols), no_update
            if trigger_type == "symbol-suggestion-option" and trigger_symbol:
                updated_symbols = _parse_symbol_text([*selected_symbols, trigger_symbol])
                return _format_symbol_text(updated_symbols), ""

        if triggered_id == "symbol-query-input":
            query_symbols = _parse_symbol_text(query)
            if not query_symbols:
                return no_update, ""
            updated_symbols = _parse_symbol_text([*selected_symbols, *query_symbols])
            return _format_symbol_text(updated_symbols), ""

        return no_update, no_update

    @app.callback(
        Output("symbol-search-status", "children"),
        [Input("ticker-input", "value")],
    )
    def update_symbol_input_status(symbol_text):
        """Show lightweight validation guidance for the selected symbols."""
        selected_symbols = _parse_symbol_text(symbol_text)
        if not selected_symbols:
            return html.Div(
                [
                    html.I(className="fa-solid fa-circle-exclamation me-2"),
                    "Enter at least one stock or crypto symbol.",
                ],
                className="symbol-search-empty",
            )

        return html.Div(
            [
                html.Span(
                    [
                        html.I(className="fa-solid fa-check me-1"),
                        f"{len(selected_symbols)} selected",
                    ],
                    className="symbol-search-count",
                ),
                html.Span("Type to search, click a suggestion to add it, or press Enter to add a custom symbol.", className="symbol-search-copy"),
            ],
            className="symbol-search-summary",
        )

    @app.callback(
        Output("research-depth-info", "children"),
        [Input("research-depth", "value")]
    )
    def update_research_depth_info(selected_depth):
        """Update the research depth information display based on selection"""
        if not selected_depth:
            return ""

        research_depth_info = {
            "Shallow": {
                "description": "Fast pass with minimal debate.",
                "settings": [
                    "1 debate round",
                    "1 risk round",
                ],
                "tone": "info",
                "icon": "fa-gauge-high",
            },
            "Medium": {
                "description": "Balanced discussion depth.",
                "settings": [
                    "3 debate rounds",
                    "3 risk rounds",
                ],
                "tone": "warning",
                "icon": "fa-scale-balanced",
            },
            "Deep": {
                "description": "Most thorough agent debate.",
                "settings": [
                    "5 debate rounds",
                    "5 risk rounds",
                ],
                "tone": "success",
                "icon": "fa-layer-group",
            }
        }

        info = research_depth_info.get(selected_depth, {})
        if not info:
            return ""

        return _status_panel(
            f"{selected_depth} mode",
            info["description"],
            info["settings"],
            tone=info["tone"],
            icon=info["icon"],
        )

    @app.callback(
        Output("trading-horizon-info", "children"),
        [Input("trading-horizon", "value")]
    )
    def update_trading_horizon_info(trading_horizon):
        """Show the selected holding-period profile."""
        horizon = (trading_horizon or "swing").lower()
        profile = {
            "swing": (
                "Swing horizon",
                "2-10 trading days using 1h/4h/1d structure.",
                ["Entry, stop, target", "Normal execution rules"],
                "info",
                "fa-chart-line",
            ),
            "position": (
                "Position horizon",
                "1-3 months using daily and weekly trend evidence.",
                ["Trend thesis", "Research-only by default"],
                "warning",
                "fa-timeline",
            ),
            "trend": (
                "Trend horizon",
                "3-6 months using weekly and monthly regime evidence.",
                ["Quarterly thesis", "Research-only by default"],
                "warning",
                "fa-arrow-trend-up",
            ),
        }.get(horizon)
        if not profile:
            return ""
        title, description, settings, tone, icon = profile
        return _status_panel(title, description, settings, tone=tone, icon=icon)

    @app.callback(
        Output("market-hours-validation", "children"),
        [Input("market-hours-input", "value")]
    )
    def validate_market_hours_input(hours_input):
        """Validate market hours input and show validation message"""
        if not hours_input or not hours_input.strip():
            return ""

        from webui.utils.market_hours import validate_market_hours

        is_valid, hours, error_msg = validate_market_hours(hours_input)

        if not is_valid:
            return dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                error_msg
            ], color="danger", className="config-inline-alert mb-2")
        else:
            # Format hours for display
            formatted_hours = []
            for hour in hours:
                if hour < 12:
                    formatted_hours.append(f"{hour}:00 AM")
                else:
                    formatted_hours.append(f"{hour-12}:00 PM" if hour > 12 else "12:00 PM")

            hours_str = " and ".join(formatted_hours)
            return dbc.Alert([
                html.I(className="fas fa-check-circle me-2"),
                f"Valid trading hours: {hours_str} EST/EDT"
            ], color="success", className="config-inline-alert mb-2")

    @app.callback(
        [Output("loop-enabled", "value"),
         Output("market-hour-enabled", "value"),
         Output("loop-interval", "disabled"),
         Output("market-hours-input", "disabled")],
        [Input("loop-enabled", "value"),
         Input("market-hour-enabled", "value")],
        prevent_initial_call=True
    )
    def mutual_exclusive_scheduling_modes(loop_enabled, market_hour_enabled):
        """Ensure only one scheduling mode can be enabled at a time"""
        ctx = dash.callback_context
        if not ctx.triggered:
            return loop_enabled, market_hour_enabled, False, False

        trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

        if trigger_id == "loop-enabled" and loop_enabled:
            # Loop mode was enabled, disable market hour mode
            return True, False, False, True
        elif trigger_id == "market-hour-enabled" and market_hour_enabled:
            # Market hour mode was enabled, disable loop mode
            return False, True, True, False
        else:
            # Either mode was disabled, enable both inputs
            return loop_enabled, market_hour_enabled, not loop_enabled, not market_hour_enabled

    @app.callback(
        Output("scheduling-mode-info", "children"),
        [Input("loop-enabled", "value"),
         Input("loop-interval", "value"),
         Input("market-hour-enabled", "value"),
         Input("market-hours-input", "value")]
    )
    def update_scheduling_mode_info(loop_enabled, loop_interval, market_hour_enabled, market_hours_input):
        """Update the scheduling mode information display based on settings"""
        if market_hour_enabled:
            from webui.utils.market_hours import validate_market_hours, format_market_hours_info

            if not market_hours_input or not market_hours_input.strip():
                return _status_panel(
                    "Market-hour mode needs hours",
                    "Enter one or more Eastern Time hours.",
                    ["Example: 10,15"],
                    tone="danger",
                    icon="fa-triangle-exclamation",
                )

            is_valid, hours, error_msg = validate_market_hours(market_hours_input)

            if not is_valid:
                return _status_panel(
                    "Invalid market hours",
                    error_msg,
                    tone="danger",
                    icon="fa-triangle-exclamation",
                )

            hours_info = format_market_hours_info(hours)
            next_executions = [
                f"Next {exec_info['formatted_hour']}: {exec_info['next_formatted']}"
                for exec_info in hours_info["next_executions"]
            ]
            return _status_panel(
                "Market-hour mode enabled",
                hours_info["formatted_hours"],
                next_executions[:3],
                tone="success",
                icon="fa-calendar-check",
            )

        elif loop_enabled:
            interval = loop_interval if loop_interval and loop_interval > 0 else 60
            return _status_panel(
                "Loop mode enabled",
                f"Runs again every {interval} minutes.",
                ["Sequential symbols", "Manual stop"],
                tone="warning",
                icon="fa-rotate",
            )

        else:
            return _status_panel(
                "Single run",
                "Runs once for the selected symbols.",
                ["Sequential symbols", "Stops when complete"],
                tone="neutral",
                icon="fa-play",
            )

    @app.callback(
        Output("control-button-container", "children"),
        [Input("refresh-interval", "n_intervals")]
    )
    def update_control_button(n_intervals):
        """Update the control button (Start/Stop) based on current state"""
        if app_state.analysis_running or app_state.loop_enabled or app_state.market_hour_enabled:
            return dbc.Button(
                [html.I(className="fa-solid fa-stop me-2"), "Stop Analysis"],
                id="control-btn",
                color="danger",
                size="lg",
                className="w-100 config-primary-action"
            )
        else:
            return dbc.Button(
                [html.I(className="fa-solid fa-play me-2"), "Start Analysis"],
                id="control-btn",
                color="primary",
                size="lg",
                className="w-100 config-primary-action"
            )

    @app.callback(
        Output("trading-mode-info", "children"),
        [Input("allow-shorts", "value")]
    )
    def update_trading_mode_info(allow_shorts):
        """Update the trading mode information display based on allow shorts selection"""
        if allow_shorts is None:
            return ""

        if allow_shorts:
            return _status_panel(
                "Shorts enabled",
                "Recommendations can include long and short positions.",
                ["Higher risk", "Margin required"],
                tone="danger",
                icon="fa-arrow-trend-down",
            )

        return _status_panel(
            "Long-only",
            "Recommendations stay on buy or hold decisions.",
            ["Lower complexity", "No short exposure"],
            tone="success",
            icon="fa-arrow-trend-up",
        )

    @app.callback(
        Output("trade-after-analyze-info", "children"),
        [Input("trade-after-analyze", "value"),
         Input("trade-dollar-amount", "value"),
         Input("trading-horizon", "value"),
         Input("trend-execution-enabled", "value")]
    )
    def update_trade_after_analyze_info(
        trade_enabled,
        dollar_amount,
        trading_horizon,
        trend_execution_enabled,
    ):
        """Update the trade after analyze information display"""
        if not trade_enabled:
            return _status_panel(
                "Manual trading",
                "Analysis results are shown without placing orders.",
                ["No automatic orders"],
                tone="neutral",
                icon="fa-hand-pointer",
            )

        amount = dollar_amount if dollar_amount and dollar_amount > 0 else 1000
        horizon = (trading_horizon or "swing").lower()

        if horizon in {"position", "trend"} and not trend_execution_enabled:
            return _status_panel(
                "Trend research-only",
                "Order execution is blocked until trend execution is explicitly enabled.",
                ["Analysis only", "No Alpaca order"],
                tone="warning",
                icon="fa-lock",
            )

        return _status_panel(
            "Order execution enabled",
            f"${amount:.2f} per order through the configured Alpaca account.",
            ["Review account mode", "Uses fractional shares"],
            tone="warning",
            icon="fa-bolt",
        )

    # Major callback for analysis control
    @app.callback(
        [Output("result-text", "children"),
         Output("app-store", "data"),
         Output("chart-pagination", "max_value"),
         Output("chart-pagination", "active_page"),
         Output("report-pagination", "max_value"),
         Output("report-pagination", "active_page")],
        [Input("control-btn", "n_clicks"),
         Input("control-btn", "children")],
        [State("ticker-input", "value"),
         State("analyst-market", "value"),
         State("analyst-social", "value"),
         State("analyst-news", "value"),
         State("analyst-fundamentals", "value"),
         State("analyst-macro", "value"),
         State("research-depth", "value"),
         State("llm-provider", "value"),
         State("backend-url", "value"),
         State("output-language", "value"),
         State("checkpoint-enabled", "value"),
         State("quick-llm", "value"),
         State("deep-llm", "value"),
         State("quick-llm-custom-model", "value"),
         State("deep-llm-custom-model", "value"),
         State("google-thinking-level", "value"),
         State("anthropic-effort", "value"),
         State("quick-llm-reasoning-effort", "value"),
         State("quick-llm-verbosity", "value"),
         State("quick-llm-summary", "value"),
         State("quick-llm-temperature", "value"),
         State("quick-llm-top-p", "value"),
         State("quick-llm-max-output-tokens", "value"),
         State("quick-llm-store", "value"),
         State("quick-llm-parallel-tool-calls", "value"),
         State("deep-llm-reasoning-effort", "value"),
         State("deep-llm-verbosity", "value"),
         State("deep-llm-summary", "value"),
         State("deep-llm-temperature", "value"),
         State("deep-llm-top-p", "value"),
         State("deep-llm-max-output-tokens", "value"),
         State("deep-llm-store", "value"),
         State("deep-llm-parallel-tool-calls", "value"),
         State("allow-shorts", "value"),
         State("trading-horizon", "value"),
         State("loop-enabled", "value"),
         State("loop-interval", "value"),
         State("trade-after-analyze", "value"),
         State("trend-execution-enabled", "value"),
         State("trade-dollar-amount", "value"),
         State("market-hour-enabled", "value"),
         State("market-hours-input", "value"),
         State("app-store", "data")]
    )
    def on_control_button_click(n_clicks, button_children, tickers, analysts_market, analysts_social, analysts_news,
                               analysts_fundamentals, analysts_macro, research_depth,
                               llm_provider, backend_url, output_language, checkpoint_enabled,
                               quick_llm, deep_llm, quick_llm_custom_model, deep_llm_custom_model,
                               google_thinking_level, anthropic_effort,
                               quick_reasoning_effort, quick_verbosity, quick_summary, quick_temperature,
                               quick_top_p, quick_max_output_tokens, quick_store, quick_parallel_tool_calls,
                               deep_reasoning_effort, deep_verbosity, deep_summary, deep_temperature,
                               deep_top_p, deep_max_output_tokens, deep_store, deep_parallel_tool_calls,
                               allow_shorts, trading_horizon, loop_enabled, loop_interval,
                               trade_enabled, trend_execution_enabled, trade_amount,
                               market_hour_enabled, market_hours_input, current_store_data):
        """Handle control button clicks"""
        # Detect which property triggered this callback
        triggered_prop = None
        if dash.callback_context.triggered:
            triggered_prop = dash.callback_context.triggered[0]['prop_id']

        # If the callback was invoked solely because the button *label* changed, ignore it
        if triggered_prop == "control-btn.children":
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Ignore callbacks caused by the periodic re-rendering of the button itself
        if triggered_prop == "control-btn.n_clicks" and (n_clicks is None or n_clicks == 0):
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Real user click handling begins here
        if n_clicks is None:
            return "", {}, 1, 1, 1, 1

        # Always use current/real-time data for analysis
        from datetime import datetime

        # Determine action based on current state
        is_stop_action = app_state.analysis_running or app_state.loop_enabled or app_state.market_hour_enabled

        # Handle stop action
        if is_stop_action:
            if app_state.loop_enabled:
                app_state.stop_loop_mode()
                symbols = list(app_state.symbol_states.keys()) or _symbols_from_store(current_store_data)
                store_data = dict(current_store_data or {})
                store_data.update(
                    {
                        "analysis_started": bool(symbols),
                        "analysis_status": "stopped",
                        "timestamp": time.time(),
                        "symbols": symbols,
                        "num_symbols": len(symbols),
                        "reports": {
                            symbol: _state_reports_for_store(symbol)
                            for symbol in symbols
                        },
                        "message": "Loop analysis stopped.",
                    }
                )
                max_pages = max(1, len(symbols))
                active_page = 1
                return "Loop analysis stopped.", store_data, max_pages, active_page, max_pages, active_page
            elif app_state.market_hour_enabled:
                app_state.stop_market_hour_mode()
                symbols = list(app_state.symbol_states.keys()) or _symbols_from_store(current_store_data)
                store_data = dict(current_store_data or {})
                store_data.update(
                    {
                        "analysis_started": bool(symbols),
                        "analysis_status": "stopped",
                        "timestamp": time.time(),
                        "symbols": symbols,
                        "num_symbols": len(symbols),
                        "reports": {
                            symbol: _state_reports_for_store(symbol)
                            for symbol in symbols
                        },
                        "message": "Market hour analysis stopped.",
                    }
                )
                max_pages = max(1, len(symbols))
                active_page = 1
                return "Market hour analysis stopped.", store_data, max_pages, active_page, max_pages, active_page
            else:
                app_state.analysis_running = False
                symbols = list(app_state.symbol_states.keys()) or _symbols_from_store(current_store_data)
                app_state.finish_analysis_run()
                store_data = dict(current_store_data or {})
                store_data.update(
                    {
                        "analysis_started": bool(symbols),
                        "analysis_status": "stopped",
                        "timestamp": time.time(),
                        "symbols": symbols,
                        "num_symbols": len(symbols),
                        "reports": {
                            symbol: _state_reports_for_store(symbol)
                            for symbol in symbols
                        },
                        "message": "Analysis stopped.",
                    }
                )
                max_pages = max(1, len(symbols))
                active_page = 1
                return "Analysis stopped.", store_data, max_pages, active_page, max_pages, active_page

        # Handle start action
        if app_state.analysis_running:
            return "Analysis already in progress. Please wait.", dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        symbols = [s.strip().upper() for s in tickers.split(',') if s.strip()]
        if not symbols:
            return "Please enter at least one stock symbol.", {}, 1, 1, 1, 1

        if not app_state.analysis_running:
            app_state.reset()

        # Store selected analysts for the status table
        app_state.active_analysts = []
        if analysts_market: app_state.active_analysts.append("Market Analyst")
        if analysts_social: app_state.active_analysts.append("Social Analyst")
        if analysts_news: app_state.active_analysts.append("News Analyst")
        if analysts_fundamentals: app_state.active_analysts.append("Fundamentals Analyst")
        if analysts_macro: app_state.active_analysts.append("Macro Analyst")

        quick_llm, quick_model_error = _resolve_runtime_model("quick thinker", quick_llm, quick_llm_custom_model)
        if quick_model_error:
            return quick_model_error, {}, 1, 1, 1, 1
        deep_llm, deep_model_error = _resolve_runtime_model("deep thinker", deep_llm, deep_llm_custom_model)
        if deep_model_error:
            return deep_model_error, {}, 1, 1, 1, 1

        quick_llm_params = _collect_llm_params(
            quick_llm,
            "quick",
            quick_reasoning_effort,
            quick_verbosity,
            quick_summary,
            quick_temperature,
            quick_top_p,
            quick_max_output_tokens,
            quick_store,
            quick_parallel_tool_calls,
        )
        deep_llm_params = _collect_llm_params(
            deep_llm,
            "deep",
            deep_reasoning_effort,
            deep_verbosity,
            deep_summary,
            deep_temperature,
            deep_top_p,
            deep_max_output_tokens,
            deep_store,
            deep_parallel_tool_calls,
        )
        if (llm_provider or "openai") not in ("openai", "local_openai"):
            quick_llm_params = {}
            deep_llm_params = {}

        provider_metadata = get_provider_ui_metadata(llm_provider)
        backend_url = (backend_url or "").strip() if provider_metadata.get("backend_visible") else ""
        provider_settings = {
            "google_thinking_level": google_thinking_level or None,
            "anthropic_effort": anthropic_effort or None,
        }

        # Set loop configuration
        app_state.loop_interval_minutes = loop_interval if loop_interval and loop_interval > 0 else 60

        # Store trading configuration
        app_state.trade_enabled = trade_enabled
        app_state.trade_amount = trade_amount if trade_amount and trade_amount > 0 else 1000
        horizon = (trading_horizon or "swing").lower()
        if horizon not in {"swing", "position", "trend"}:
            horizon = "swing"

        # Validate market hour configuration if enabled
        if market_hour_enabled:
            from webui.utils.market_hours import validate_market_hours
            is_valid, market_hours_list, error_msg = validate_market_hours(market_hours_input)
            if not is_valid:
                return f"Invalid market hours: {error_msg}", {}, 1, 1, 1, 1

        num_symbols = len(symbols)

        # Initialize symbol states IMMEDIATELY so pagination works right away
        for symbol in symbols:
            app_state.init_symbol_state(symbol)

        def analysis_thread():
            if market_hour_enabled:
                # Start market hour mode with scheduling logic
                market_hour_config = {
                    'analysts_market': analysts_market,
                    'analysts_social': analysts_social,
                    'analysts_news': analysts_news,
                    'analysts_fundamentals': analysts_fundamentals,
                    'analysts_macro': analysts_macro,
                    'research_depth': research_depth,
                    'allow_shorts': allow_shorts,
                    'trading_horizon': horizon,
                    'trend_execution_enabled': bool(trend_execution_enabled),
                    'llm_provider': llm_provider,
                    'backend_url': backend_url,
                    'output_language': output_language,
                    'checkpoint_enabled': checkpoint_enabled,
                    'quick_llm': quick_llm,
                    'deep_llm': deep_llm,
                    'quick_llm_params': quick_llm_params,
                    'deep_llm_params': deep_llm_params,
                    **provider_settings,
                    'trade_enabled': trade_enabled,
                    'trend_execution_enabled': bool(trend_execution_enabled),
                    'trade_amount': trade_amount
                }
                app_state.start_market_hour_mode(symbols, market_hour_config, market_hours_list)

                # Market hour scheduling loop
                import datetime
                import pytz
                from webui.utils.market_hours import get_next_market_datetime, is_market_open

                eastern = pytz.timezone('US/Eastern')
                utc = pytz.utc

                while not app_state.stop_market_hour:
                    # Compute the schedule from current UTC time projected into Eastern.
                    now = datetime.datetime.now(utc).astimezone(eastern)
                    next_execution_times = []

                    for hour in app_state.market_hours:
                        next_dt = get_next_market_datetime(hour, now)
                        next_execution_times.append((hour, next_dt))

                    # Sort by next execution time
                    next_execution_times.sort(key=lambda x: x[1])
                    next_hour, next_dt = next_execution_times[0]

                    print(f"[MARKET_HOUR] Next execution: {next_dt.strftime('%A, %B %d at %I:%M %p %Z')} (Hour {next_hour})")

                    # Wait until next execution time
                    while datetime.datetime.now(utc).astimezone(eastern) < next_dt and not app_state.stop_market_hour:
                        time.sleep(60)  # Check every minute

                    if app_state.stop_market_hour:
                        break

                    # Check if market is actually open
                    is_open, reason = is_market_open()
                    if not is_open:
                        print(f"[MARKET_HOUR] Market is closed: {reason}. Waiting for next execution time.")
                        continue

                    print(f"[MARKET_HOUR] Market is open, starting analysis at {next_hour}:00")

                    # Reset states for new analysis
                    app_state.reset_for_loop()

                    # Initialize symbol states
                    for symbol in symbols:
                        app_state.init_symbol_state(symbol)

                    # Add symbols to queue and run analysis
                    app_state.add_symbols_to_queue(symbols)

                    while app_state.analysis_queue and not app_state.stop_market_hour:
                        symbol = app_state.get_next_symbol()
                        if symbol:
                            print(f"[MARKET_HOUR] Analyzing {symbol} at {next_hour}:00 with current market data...")
                            start_analysis(
                                symbol,
                                analysts_market, analysts_social, analysts_news, analysts_fundamentals, analysts_macro,
                                research_depth, allow_shorts, quick_llm, deep_llm,
                                quick_llm_params, deep_llm_params,
                                llm_provider=llm_provider,
                                backend_url=backend_url,
                                output_language=output_language,
                                checkpoint_enabled=checkpoint_enabled,
                                provider_settings=provider_settings,
                                trading_horizon=horizon,
                                trend_execution_enabled=trend_execution_enabled,
                            )

                            if app_state.stop_market_hour:
                                break

                    if not app_state.stop_market_hour:
                        print(f"[MARKET_HOUR] Analysis completed for {next_hour}:00. Waiting for next execution time.")

            elif loop_enabled:
                # Start loop mode
                loop_config = {
                    'analysts_market': analysts_market,
                    'analysts_social': analysts_social,
                    'analysts_news': analysts_news,
                    'analysts_fundamentals': analysts_fundamentals,
                    'analysts_macro': analysts_macro,
                    'research_depth': research_depth,
                    'allow_shorts': allow_shorts,
                    'trading_horizon': horizon,
                    'trend_execution_enabled': bool(trend_execution_enabled),
                    'llm_provider': llm_provider,
                    'backend_url': backend_url,
                    'output_language': output_language,
                    'checkpoint_enabled': checkpoint_enabled,
                    'quick_llm': quick_llm,
                    'deep_llm': deep_llm,
                    'quick_llm_params': quick_llm_params,
                    'deep_llm_params': deep_llm_params,
                    **provider_settings,
                    'trade_enabled': trade_enabled,
                    'trend_execution_enabled': bool(trend_execution_enabled),
                    'trade_amount': trade_amount
                }
                app_state.start_loop(symbols, loop_config)

                loop_iteration = 1
                while not app_state.stop_loop:
                    print(f"[LOOP] Starting iteration {loop_iteration}")

                    # States already initialized above, just add to queue
                    app_state.add_symbols_to_queue(symbols)

                    # Run analysis for all symbols
                    while app_state.analysis_queue and not app_state.stop_loop:
                        symbol = app_state.get_next_symbol()
                        if symbol:
                            print(f"[LOOP] Analyzing {symbol} with current market data...")
                            start_analysis(
                                symbol,
                                analysts_market, analysts_social, analysts_news, analysts_fundamentals, analysts_macro,
                                research_depth, allow_shorts, quick_llm, deep_llm,
                                quick_llm_params, deep_llm_params,
                                llm_provider=llm_provider,
                                backend_url=backend_url,
                                output_language=output_language,
                                checkpoint_enabled=checkpoint_enabled,
                                provider_settings=provider_settings,
                                trading_horizon=horizon,
                                trend_execution_enabled=trend_execution_enabled,
                            )

                    if app_state.stop_loop:
                        break

                    print(f"[LOOP] Iteration {loop_iteration} completed. Waiting {app_state.loop_interval_minutes} minutes...")

                    # Wait for the specified interval (checking for stop every 30 seconds)
                    wait_time = app_state.loop_interval_minutes * 60  # Convert to seconds
                    elapsed = 0
                    while elapsed < wait_time and not app_state.stop_loop:
                        time.sleep(min(30, wait_time - elapsed))
                        elapsed += 30

                    if not app_state.stop_loop:
                        # Reset analysis results for next iteration but keep states for pagination
                        app_state.reset_for_loop()
                        loop_iteration += 1

                print("[LOOP] Loop stopped")
            else:
                # Single run mode (original behavior) - use current date
                # States already initialized above, just add to queue
                app_state.add_symbols_to_queue(symbols)

                while app_state.analysis_queue:
                    symbol = app_state.get_next_symbol()
                    if symbol:
                        print(f"[SINGLE] Analyzing {symbol} with current market data...")
                        start_analysis(
                            symbol,
                            analysts_market, analysts_social, analysts_news, analysts_fundamentals, analysts_macro,
                            research_depth, allow_shorts, quick_llm, deep_llm,
                            quick_llm_params, deep_llm_params,
                            llm_provider=llm_provider,
                            backend_url=backend_url,
                            output_language=output_language,
                            checkpoint_enabled=checkpoint_enabled,
                            provider_settings=provider_settings,
                            trading_horizon=horizon,
                            trend_execution_enabled=trend_execution_enabled,
                        )

            if market_hour_enabled:
                app_state.analysis_running = False
            else:
                app_state.finish_analysis_run()

        if not app_state.analysis_running:
            app_state.analysis_running = True
            thread = threading.Thread(target=analysis_thread)
            thread.start()

        if market_hour_enabled:
            mode_text = "market hour mode"
            # Format hours for display
            formatted_hours = []
            for hour in market_hours_list:
                if hour < 12:
                    formatted_hours.append(f"{hour}:00 AM")
                else:
                    formatted_hours.append(f"{hour-12}:00 PM" if hour > 12 else "12:00 PM")
            interval_text = f" (at {' and '.join(formatted_hours)} EST/EDT)"
        elif loop_enabled:
            mode_text = "loop mode"
            interval_text = f" (every {app_state.loop_interval_minutes} minutes)"
        else:
            mode_text = "single run mode"
            interval_text = ""

        research_only_note = (
            " Trend horizon is research-only unless trend execution is explicitly enabled."
            if horizon in {"position", "trend"} and not trend_execution_enabled
            else ""
        )
        start_message = (
            f"Starting real-time analysis for {', '.join(symbols)} in {mode_text}{interval_text} "
            f"using {horizon} horizon and current market data.{research_only_note}"
        )
        store_data = _build_analysis_store_data(
            symbols,
            mode_text,
            interval_text,
            horizon,
            trend_execution_enabled,
            "running",
            start_message,
        )
        return start_message, store_data, num_symbols, 1, num_symbols, 1

    @app.callback(
        Output("app-store", "data", allow_duplicate=True),
        [Input("medium-refresh-interval", "n_intervals")],
        [State("app-store", "data")],
        prevent_initial_call=True,
    )
    def persist_completed_reports(n_intervals, store_data):
        if not store_data or not store_data.get("analysis_started"):
            return dash.no_update
        symbols = _symbols_from_store(store_data)
        if not symbols or app_state.analysis_running:
            return dash.no_update
        if not app_state.symbol_states:
            return dash.no_update

        reports_by_symbol = {
            symbol: _state_reports_for_store(symbol)
            for symbol in symbols
            if symbol in app_state.symbol_states
        }
        if not any(reports_by_symbol.values()):
            return dash.no_update

        status = "completed" if all(
            (app_state.get_state(symbol) or {}).get("analysis_complete", False)
            for symbol in reports_by_symbol
        ) else store_data.get("analysis_status", "running")
        message = (
            f"Analysis complete for {', '.join(symbols)}. Reports are available."
            if status == "completed"
            else store_data.get("message", "")
        )
        updated = dict(store_data)
        updated.update(
            {
                "analysis_status": status,
                "timestamp": time.time(),
                "reports": reports_by_symbol,
                "message": message,
            }
        )
        return updated

    @app.callback(
        Output("app-store", "data", allow_duplicate=True),
        [Input("settings-store", "data")],
        [State("app-store", "data")],
        prevent_initial_call=True,
    )
    def restore_latest_reports_from_settings(settings_data, current_store_data):
        if current_store_data and current_store_data.get("analysis_started"):
            return dash.no_update
        if not isinstance(settings_data, dict):
            return dash.no_update

        symbols = _parse_symbol_text(settings_data.get("ticker_input"))
        if not symbols:
            return dash.no_update

        recovered_by_symbol = _reports_from_latest_runs(symbols)
        if not recovered_by_symbol:
            return dash.no_update

        restored_symbols = [symbol for symbol in symbols if symbol in recovered_by_symbol]
        reports_by_symbol = {
            symbol: recovered_by_symbol[symbol].get("reports") or {}
            for symbol in restored_symbols
        }
        store_data = _build_analysis_store_data(
            restored_symbols,
            "restored latest run",
            "",
            settings_data.get("trading_horizon") or "swing",
            settings_data.get("trend_execution_enabled", False),
            "restored",
            f"Restored latest saved reports for {', '.join(restored_symbols)}.",
        )
        store_data["reports"] = reports_by_symbol
        return store_data

    @app.callback(
        [Output("chart-pagination", "max_value", allow_duplicate=True),
         Output("chart-pagination", "active_page", allow_duplicate=True),
         Output("report-pagination", "max_value", allow_duplicate=True),
         Output("report-pagination", "active_page", allow_duplicate=True)],
        [Input("app-store", "data")],
        prevent_initial_call=True
    )
    def restore_pagination_on_refresh(store_data):
        """Restore pagination and symbol states after page refresh"""
        if not store_data or not store_data.get("symbols"):
            # No stored data, return defaults
            print("[RESTORE] No stored data found, returning defaults")
            return 1, 1, 1, 1

        symbols = store_data.get("symbols", [])
        num_symbols = len(symbols)

        # Restore symbol states if they don't exist (e.g., after page refresh)
        if not app_state.symbol_states and store_data.get("reports"):
            print(f"[RESTORE] Restoring persisted reports for {symbols}")
            stored_reports = store_data.get("reports") or {}
            for symbol in symbols:
                _build_restored_symbol_state(symbol, stored_reports.get(symbol, {}))
        elif not app_state.symbol_states and store_data.get("analysis_started"):
            print(f"[RESTORE] Restoring latest run reports for {symbols}")
            for symbol in symbols:
                _restore_symbol_from_latest_run(symbol)
        elif app_state.analysis_running and (
            not app_state.symbol_states or len(app_state.symbol_states) != num_symbols
        ):
            print(f"[RESTORE] Restoring symbol states for {symbols} after page refresh")
            for symbol in symbols:
                if symbol not in app_state.symbol_states:
                    app_state.init_symbol_state(symbol)

            # Set current symbol to first one if none is set
            if not app_state.current_symbol and symbols:
                app_state.set_current_symbol(symbols[0])
                print(f"[RESTORE] Set current symbol to {symbols[0]}")
        else:
            print(f"[RESTORE] Symbol states already exist for {list(app_state.symbol_states.keys())}")

        app_state.ensure_current_symbol()
        active_symbol = app_state.current_symbol
        active_page = symbols.index(active_symbol) + 1 if active_symbol in symbols else 1

        print(f"[RESTORE] Restoring pagination: max_value={num_symbols}, active_page={active_page}")
        return num_symbols, active_page, num_symbols, active_page

    @app.callback(
        Output("result-text", "children", allow_duplicate=True),
        [Input("app-store", "data")],
        prevent_initial_call=True
    )
    def restore_analysis_status_on_refresh(store_data):
        """Restore analysis status text after page refresh"""
        if not store_data or not store_data.get("analysis_started"):
            return ""

        symbols = store_data.get("symbols", [])
        mode = store_data.get("mode", "mode")
        interval_text = store_data.get("interval_text", "")
        status = store_data.get("analysis_status")

        if symbols:
            if status in {"completed", "failed", "stopped"}:
                return store_data.get("message") or f"Analysis data for {', '.join(symbols)} is available ({mode}{interval_text})."
            return f"📄 Page refreshed - Analysis data for {', '.join(symbols)} has been restored ({mode}{interval_text}). All symbol pages should now be available."

        return ""

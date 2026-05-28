"""
webui/components/analysis.py
"""

import time
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.graph.checkpointer import clear_checkpoint
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.run_logger import get_run_audit_logger
from tradingagents.eval import EpisodeLedger
from tradingagents.agents.utils.agent_trading_modes import extract_recommendation
from tradingagents.trade_lifecycle import TradeMonitorService, persist_approved_plan
from webui.utils.state import app_state
from webui.utils.charts import create_chart


def _safe_ledger(config):
    if not config.get("episode_ledger_enabled", True):
        return None
    try:
        return EpisodeLedger(config.get("episode_ledger_path"))
    except Exception as exc:
        print(f"[EVAL] Episode ledger unavailable: {exc}")
        return None


def _ledger_start(ledger, run_id, ticker, trade_date, config, selected_analysts, metadata):
    if not ledger or not run_id:
        return
    try:
        episode_metadata = {
            "data_leakage_risk": "high" if config.get("online_tools", True) else "low",
            **metadata,
            **(config.get("episode_ledger_metadata") or {}),
        }
        ledger.start_episode(
            run_id=run_id,
            symbol=ticker,
            trade_date=str(trade_date),
            config=config,
            selected_analysts=selected_analysts,
            metadata=episode_metadata,
        )
    except Exception as exc:
        print(f"[EVAL] Failed to start episode ledger entry: {exc}")


def _ledger_complete(ledger, run_id, final_state, final_signal, audit_path):
    if not ledger or not run_id:
        return
    try:
        ledger.complete_episode(run_id, final_state, final_signal, audit_path)
    except Exception as exc:
        print(f"[EVAL] Failed to complete episode ledger entry: {exc}")


def _ledger_fail(ledger, run_id, error_message):
    if not ledger or not run_id:
        return
    try:
        ledger.fail_episode(run_id, error_message)
    except Exception as exc:
        print(f"[EVAL] Failed to mark episode failure: {exc}")


def _latest_logged_agent_output(run_logger, run_id, symbol):
    if not run_id:
        return {}
    with run_logger._lock:
        run_data = run_logger._active_runs.get(run_id)
        if not run_data:
            return {}
        output = {}
        for event in run_data.get("events", []):
            if event.get("type") != "agent_output":
                continue
            payload = event.get("payload") or {}
            output_type = payload.get("output_type")
            content = payload.get("content")
            if output_type and content:
                output[output_type] = content
        return output


def _persist_partial_run_state(run_logger, run_id, symbol, current_state):
    """Keep UI reports visible when a run fails or is interrupted before final_state."""
    if not current_state:
        return
    try:
        logged_outputs = _latest_logged_agent_output(run_logger, run_id, symbol)
        reports = current_state.setdefault("current_reports", {})
        output_map = {
            "market_report": "market_report",
            "sentiment_report": "sentiment_report",
            "news_report": "news_report",
            "fundamentals_report": "fundamentals_report",
            "macro_report": "macro_report",
            "investment_plan": "research_manager_report",
            "trader_investment_plan": "trader_investment_plan",
            "final_trade_decision": "final_trade_decision",
        }
        for output_type, report_type in output_map.items():
            content = logged_outputs.get(output_type)
            if content and not reports.get(report_type):
                reports[report_type] = content
        if reports.get("final_trade_decision") and not reports.get("portfolio_decision"):
            reports["portfolio_decision"] = reports["final_trade_decision"]

        final_decision = reports.get("final_trade_decision")
        if final_decision:
            decision = extract_recommendation(
                final_decision,
                current_state.get("trading_mode", "investment"),
            ) or current_state.get("recommended_action")
            if decision:
                current_state["recommended_action"] = decision
            current_state["analysis_complete"] = True
            current_state["analysis_results"] = {
                "ticker": symbol,
                "date": current_state.get("trade_date") or "",
                "decision": decision or "No decision",
                "trading_horizon": current_state.get("trading_horizon", "swing"),
                "trend_research_only": (
                    current_state.get("trading_horizon") in {"position", "trend"}
                    and not current_state.get("trend_execution_enabled", False)
                ),
            }
        app_state.update_reports_count()
        app_state.needs_ui_update = True
    except Exception as exc:
        print(f"[STATE] Failed to persist partial run state for {symbol}: {exc}")


def execute_trade_after_analysis(
    ticker,
    allow_shorts,
    trade_amount,
    *,
    config=None,
    final_state=None,
    run_id=None,
    audit_path=None,
    persist_plan=True,
):
    """Trigger a risk-approved conditional plan through monitor + validator."""
    try:
        print(f"[TRADE] Starting conditional trade monitor pass for {ticker}")

        # Get the current state for this symbol
        state = app_state.get_state(ticker)
        if not state:
            print(f"[TRADE] No state found for {ticker}, skipping trade execution")
            return

        if not state.get("analysis_complete"):
            print(f"[TRADE] Analysis not complete for {ticker}, skipping trade execution")
            print(f"[TRADE] Analysis status: {state.get('analysis_complete', 'Unknown')}")
            return

        cfg = (config or DEFAULT_CONFIG.copy()).copy()
        cfg["allow_shorts"] = allow_shorts
        cfg["trade_amount"] = trade_amount
        cfg["trade_lifecycle_default_notional"] = trade_amount if trade_amount and trade_amount > 0 else 1000
        final_state = final_state or (state.get("analysis_results") or {}).get("full_state")
        if final_state and persist_plan:
            plan = persist_approved_plan(
                final_state,
                config=cfg,
                source_run_id=run_id,
                audit_path=audit_path,
            )
            if plan:
                state["conditional_trade_plan"] = plan.model_dump(mode="json")
                final_state["conditional_trade_plan"] = state["conditional_trade_plan"]

        monitor_result = TradeMonitorService(cfg).run_once(symbols=[ticker])
        state["trading_results"] = monitor_result

        executed = any(
            item.get("order_result", {}).get("success")
            for item in monitor_result.get("processed", [])
        )
        if executed:
            print(f"[TRADE] Conditional plan executed through validator for {ticker}")
            app_state.signal_trade_occurred()
        else:
            print(f"[TRADE] No validated paper order executed for {ticker}: {monitor_result}")

    except Exception as e:
        print(f"[TRADE] Error running conditional trade monitor for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        state = app_state.get_state(ticker)
        if state:
            state["trading_results"] = {"error": f"Conditional trade monitor error: {str(e)}"}


def run_analysis(
    ticker,
    selected_analysts,
    research_depth_config,
    allow_shorts,
    quick_llm,
    deep_llm,
    quick_llm_params=None,
    deep_llm_params=None,
    llm_provider="openai",
    backend_url=None,
    output_language="zh-CN",
    checkpoint_enabled=False,
    provider_settings=None,
    trading_horizon="swing",
    trend_execution_enabled=False,
    progress=None,
):
    """Run the trading analysis using current/real-time data

    Args:
        research_depth_config: Either a dict with "rounds" and "level" keys,
                              or an integer for backward compatibility
    """
    run_logger = get_run_audit_logger()
    run_started = False
    run_id = None
    ledger = None
    final_state = None
    current_date = None
    current_state = None

    try:
        # Always use current date for real-time analysis
        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d")

        print(f"Starting real-time analysis for {ticker} with current date: {current_date}")
        current_state = app_state.get_state(ticker)
        if not current_state:
            print(f"Error: No state found for {ticker}")
            return
        current_state["analysis_running"] = True
        current_state["analysis_complete"] = False

        # Handle both new dict format and legacy integer format
        if isinstance(research_depth_config, dict):
            depth_rounds = research_depth_config.get("rounds", 3)
            depth_level = research_depth_config.get("level", "Medium")
        else:
            # Legacy integer format - convert back to string
            depth_rounds = research_depth_config
            depth_map = {1: "Shallow", 3: "Medium", 5: "Deep"}
            depth_level = depth_map.get(research_depth_config, "Medium")

        # Create config with selected options
        config = DEFAULT_CONFIG.copy()
        config["max_debate_rounds"] = depth_rounds
        config["max_risk_discuss_rounds"] = depth_rounds
        config["research_depth"] = depth_level  # String for LLM parameter mapping
        config["allow_shorts"] = allow_shorts
        config["trading_mode"] = "trading" if allow_shorts else "investment"
        config["parallel_analysts"] = True  # Run analysts in parallel for faster execution
        config["quick_think_llm"] = quick_llm
        config["deep_think_llm"] = deep_llm
        config["quick_llm_params"] = quick_llm_params or {}
        config["deep_llm_params"] = deep_llm_params or {}
        config["llm_provider"] = llm_provider or "openai"
        config["backend_url"] = backend_url or None
        config["output_language"] = output_language or "zh-CN"
        config["checkpoint_enabled"] = bool(checkpoint_enabled)
        horizon = str(trading_horizon or "position").strip().lower()
        config["trading_horizon"] = horizon if horizon in {"swing", "position", "trend"} else "position"
        config["trend_execution_enabled"] = bool(trend_execution_enabled)
        for key, value in (provider_settings or {}).items():
            if value not in (None, ""):
                config[key] = value
        current_state["trading_horizon"] = config["trading_horizon"]
        current_state["trend_execution_enabled"] = config["trend_execution_enabled"]

        # Initialize TradingAgentsGraph
        print(f"Initializing TradingAgentsGraph with analysts: {selected_analysts}")
        graph = TradingAgentsGraph(selected_analysts, config=config, debug=True)
        ledger = _safe_ledger(config)
        graph._resolve_memory_log_outcomes(ticker, current_date)
        init_agent_state = graph.propagator.create_initial_state(ticker, current_date)
        run_logger.start_run(
            symbol=ticker,
            trade_date=current_date,
            config=config,
            metadata={"debug": True, "source": "webui_stream"},
        )
        run_id = run_logger.get_active_run_id(symbol=ticker)
        _ledger_start(
            ledger,
            run_id,
            ticker,
            current_date,
            config,
            selected_analysts,
            {"debug": True, "source": "webui_stream"},
        )
        run_started = True
        run_logger.log_state_snapshot(
            stage="initial_state",
            snapshot=init_agent_state,
            symbol=ticker,
        )

        # Status updates are now handled in the parallel execution coordinator

        # Force an initial UI update
        app_state.needs_ui_update = True

        # Run analysis with tracing using current date
        print(f"Starting graph stream for {ticker} with current market data")
        trace = []
        graph_args = graph._graph_args_for_run(ticker, current_date)
        graph_args["config"]["recursion_limit"] = 100
        compiled_graph, checkpointer_ctx = graph._graph_for_run(ticker, current_date)
        try:
            for chunk in compiled_graph.stream(init_agent_state, **graph_args):
                # Track progress
                trace.append(chunk)

                # Process intermediate results
                app_state.process_chunk_updates(chunk)

                app_state.needs_ui_update = True

                # Update progress bar if provided
                if progress is not None:
                    # Simulate progress based on steps completed
                    completed_agents = sum(1 for status in current_state["agent_statuses"].values() if status == "completed")
                    total_agents = len(current_state["agent_statuses"])
                    if total_agents > 0:
                        progress(completed_agents / total_agents)

                # Small delay to prevent UI lag
                time.sleep(0.1)
        finally:
            if checkpointer_ctx is not None:
                checkpointer_ctx.__exit__(None, None, None)

        # Extract final results
        final_state = trace[-1]
        decision = graph.process_signal(final_state["final_trade_decision"])
        graph.curr_state = final_state
        graph.ticker = ticker
        graph._log_state(current_date, final_state)

        filtered_tool_calls = [
            call for call in app_state.tool_calls_log
            if call.get("symbol") == ticker
        ]
        run_logger.log_state_snapshot(
            stage="webui_runtime_context",
            snapshot={
                "session_id": current_state.get("session_id"),
                "session_start_time": current_state.get("session_start_time"),
                "agent_prompts": current_state.get("agent_prompts", {}),
                "tool_calls": filtered_tool_calls,
                "llm_calls_count": app_state.llm_calls_count,
                "tool_calls_count": app_state.tool_calls_count,
            },
            symbol=ticker,
        )
        audit_path = run_logger.get_run_file_path(run_id=run_id, symbol=ticker)
        trade_amount_for_plan = getattr(app_state, 'trade_amount', 1000)
        plan_config = config.copy()
        plan_config["trade_lifecycle_default_notional"] = (
            trade_amount_for_plan if trade_amount_for_plan and trade_amount_for_plan > 0 else 1000
        )
        try:
            plan = persist_approved_plan(
                final_state,
                config=plan_config,
                source_run_id=run_id,
                audit_path=audit_path,
            )
            if plan:
                final_state["conditional_trade_plan"] = plan.model_dump(mode="json")
                current_state["conditional_trade_plan"] = final_state["conditional_trade_plan"]
        except Exception as exc:
            print(f"[TRADE_PLAN] Failed to persist conditional trade plan: {exc}")
        run_logger.finish_run(
            symbol=ticker,
            status="completed",
            final_state=final_state,
            final_signal=decision,
        )
        _ledger_complete(ledger, run_id, final_state, decision, audit_path)
        graph.memory_log.store_decision(
            ticker=ticker,
            trade_date=current_date,
            final_trade_decision=final_state["final_trade_decision"],
            trading_mode=final_state.get("trading_mode", config.get("trading_mode", "investment")),
            horizon=final_state.get("trading_horizon", config.get("trading_horizon", "position")),
        )
        if config.get("checkpoint_enabled", False):
            clear_checkpoint(config["data_cache_dir"], ticker, current_date)
        run_started = False

        # NEW: Persist the extracted decision so the trading engine can act on it directly
        current_state["recommended_action"] = decision

        # Mark all agents as completed
        for agent in current_state["agent_statuses"]:
            app_state.update_agent_status(agent, "completed")

        # Set final results
        current_state["analysis_results"] = {
            "ticker": ticker,
            "date": current_date,
            "decision": decision,
            "trading_horizon": config["trading_horizon"],
            "trend_research_only": config["trading_horizon"] in {"position", "trend"}
            and not config.get("trend_execution_enabled", False),
            "full_state": final_state,
        }

        # Use real chart data with current date (no end_date means most recent data)
        current_state["chart_data"] = create_chart(ticker, period="1y", end_date=None)

        current_state["analysis_complete"] = True

        # Execute trade if enabled
        trade_enabled = getattr(app_state, 'trade_enabled', False)
        trade_amount = getattr(app_state, 'trade_amount', 1000)
        print(f"[TRADE] Checking trading settings for {ticker}:")
        print(f"[TRADE]   - trade_enabled: {trade_enabled}")
        print(f"[TRADE]   - trade_amount: {trade_amount}")
        print(f"[TRADE]   - allow_shorts: {allow_shorts}")
        print(f"[TRADE]   - trading_horizon: {config['trading_horizon']}")
        print(f"[TRADE]   - trend_execution_enabled: {config['trend_execution_enabled']}")

        trend_execution_blocked = (
            config["trading_horizon"] in {"position", "trend"}
            and not config.get("trend_execution_enabled", False)
        )

        if trade_enabled and trend_execution_blocked:
            print(
                f"[TRADE] {config['trading_horizon']} horizon is research-only; "
                "skipping Alpaca execution because trend execution is not explicitly enabled"
            )
            current_state["trading_results"] = {
                "status": "research_only",
                "message": "Trend-horizon execution is disabled; analysis only.",
            }
        elif trade_enabled:
            print(f"[TRADE] Trading enabled for {ticker}, executing trade with ${trade_amount}")
            execute_trade_after_analysis(
                ticker,
                allow_shorts,
                trade_amount,
                config=plan_config,
                final_state=final_state,
                run_id=run_id,
                audit_path=audit_path,
                persist_plan=False,
            )
        else:
            print(f"[TRADE] Trading disabled for {ticker}, skipping trade execution")

        # Final UI update to show completion
        app_state.needs_ui_update = True

    except Exception as e:
        print(f"Analysis error: {e}")
        import traceback
        traceback.print_exc()
        _persist_partial_run_state(run_logger, run_id, ticker, current_state)
        if run_started:
            _ledger_fail(ledger, run_id, str(e))
            run_logger.finish_run(
                symbol=ticker,
                status="failed",
                final_state=final_state,
                error_message=str(e),
            )
            run_started = False
        if progress is not None:
            progress(1.0)  # Complete the progress bar
    finally:
        # Mark analysis as no longer running
        print(f"Real-time analysis for {ticker} completed")
        if current_state:
            _persist_partial_run_state(run_logger, run_id, ticker, current_state)
            current_state["analysis_running"] = False

    return "Real-time analysis complete"


def start_analysis(
    ticker,
    analysts_market,
    analysts_social,
    analysts_news,
    analysts_fundamentals,
    analysts_macro,
    research_depth,
    allow_shorts,
    quick_llm,
    deep_llm,
    quick_llm_params=None,
    deep_llm_params=None,
    llm_provider="openai",
    backend_url=None,
    output_language="zh-CN",
    checkpoint_enabled=False,
    provider_settings=None,
    trading_horizon="position",
    trend_execution_enabled=False,
    progress=None,
):
    """Start real-time analysis function for the UI"""

    # Parse selected analysts
    selected_analysts = []
    if analysts_market:
        selected_analysts.append("market")
    if analysts_social:
        selected_analysts.append("social")
    if analysts_news:
        selected_analysts.append("news")
    if analysts_fundamentals:
        selected_analysts.append("fundamentals")
    if analysts_macro:
        selected_analysts.append("macro")

    if not selected_analysts:
        return "Please select at least one analyst type."

    # Convert research depth to integer for debate rounds
    # Also keep the original string for LLM parameter mapping
    if research_depth == "Shallow":
        depth_rounds = 1
    elif research_depth == "Medium":
        depth_rounds = 3
    else:  # Deep
        depth_rounds = 5

    # Pass both the string (for LLM params) and rounds (for debates)
    depth_config = {"rounds": depth_rounds, "level": research_depth}

    # Create an initial chart immediately with current data
    try:
        print(f"Creating initial chart for {ticker} with current market data")
        current_state = app_state.get_state(ticker)
        if current_state:
            current_state["chart_data"] = create_chart(ticker, period="1y", end_date=None)
    except Exception as e:
        print(f"Error creating initial chart: {e}")
        import traceback
        traceback.print_exc()

    # Run analysis with current data
    run_analysis(
        ticker,
        selected_analysts,
        depth_config,
        allow_shorts,
        quick_llm,
        deep_llm,
        quick_llm_params=quick_llm_params,
        deep_llm_params=deep_llm_params,
        llm_provider=llm_provider,
        backend_url=backend_url,
        output_language=output_language,
        checkpoint_enabled=checkpoint_enabled,
        provider_settings=provider_settings,
        trading_horizon=trading_horizon,
        trend_execution_enabled=trend_execution_enabled,
        progress=progress,
    )

    # Update the status message with more details
    trading_mode = "Trading Mode (LONG/NEUTRAL/SHORT)" if allow_shorts else "Investment Mode (BUY/HOLD/SELL)"
    horizon_label = {
        "swing": "Swing",
        "position": "Position",
        "trend": "Trend",
    }.get(str(trading_horizon or "position").lower(), "Position")
    research_only_text = (
        " (research-only unless trend execution is explicitly enabled)"
        if str(trading_horizon or "position").lower() in {"position", "trend"}
        and not trend_execution_enabled
        else ""
    )
    trade_text = f" with ${getattr(app_state, 'trade_amount', 1000)} optional order execution" if getattr(app_state, 'trade_enabled', False) else ""
    return f"Real-time analysis started for {ticker} with {len(selected_analysts)} analysts in {trading_mode}, {horizon_label} horizon{research_only_text}{trade_text} using parallel execution and current market data. Status table will update automatically."

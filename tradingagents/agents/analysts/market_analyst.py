from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, ToolMessage
import time
import json
import re
from tradingagents.agents.utils.agent_trading_modes import (
    get_agent_horizon_context,
    get_horizon_context,
)
from tradingagents.agents.utils.language import language_instruction
from tradingagents.agents.utils.source_policy import is_point_in_time_mode, point_in_time_source_note
from tradingagents.prompts import load_prompt, render_prompt

# Import prompt capture utility
try:
    from webui.utils.prompt_capture import capture_agent_prompt
except ImportError:
    # Fallback for when webui is not available
    def capture_agent_prompt(report_type, prompt_content, symbol=None):
        pass


def _normalize_market_report_markdown(content: str) -> str:
    """Normalize common inline section/table patterns into readable markdown."""
    if not content:
        return content

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    section_map = {
        "conclusion": "Conclusion",
        "entry conditions": "Entry Conditions",
        "invalidation": "Invalidation",
        "risk sizing hint": "Risk Sizing Hint",
        "narrative": "Narrative",
        "summary table": "Summary Table",
    }

    for raw_label, display_label in section_map.items():
        # Handles patterns like "a) Conclusion", "b) Entry Conditions", ...
        pattern = rf"(?i)(?:^|\s)[a-f]\)\s*{re.escape(raw_label)}\b"
        normalized = re.sub(pattern, f"\n\n## {display_label}\n", normalized)

        # Handles inline labels without letter prefix.
        inline_pattern = rf"(?i)(?:^|\s){re.escape(raw_label)}\s*:"
        normalized = re.sub(inline_pattern, f"\n\n## {display_label}\n", normalized)

    # Place final proposal on its own block.
    normalized = re.sub(r"(?i)\bConclude with:\s*", "\n\n", normalized)
    normalized = re.sub(
        r"(?i)\bFINAL TRANSACTION PROPOSAL\s*:",
        "\n\nFINAL TRANSACTION PROPOSAL:",
        normalized,
    )

    # Split concatenated markdown table rows when they are on one line.
    normalized = re.sub(r"\s+\|\s+\|\s+", " |\n| ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def create_market_analyst(llm, toolkit):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]
        is_crypto = "/" in ticker or "USD" in ticker.upper() or "USDT" in ticker.upper()
        alpaca_available = is_crypto or toolkit.has_alpaca_credentials()
        horizon_context = get_horizon_context(toolkit.config)
        horizon_agent_context = get_agent_horizon_context("analyst", horizon_context)
        is_trend_horizon = horizon_context["horizon"] in ("position", "trend")
        point_in_time_mode = is_point_in_time_mode(current_date, toolkit.config)
        sellthenews_options_available = (
            toolkit.has_sellthenews("sellthenews_options_enabled")
            and not is_crypto
            and not point_in_time_mode
        )

        if toolkit.config["online_tools"] and alpaca_available:
            tools = [toolkit.get_trend_brief if is_trend_horizon else toolkit.get_technical_brief]
            tools.extend(
                [
                    toolkit.get_alpaca_data_report,
                    toolkit.get_stockstats_indicators_report_online,
                ]
            )
        elif toolkit.config["online_tools"] and not alpaca_available:
            # Keep running with offline stockstats fallback when Alpaca credentials are unavailable.
            tools = [
                toolkit.get_stockstats_indicators_report,
            ]
        else:
            tools = [toolkit.get_stockstats_indicators_report]
            if alpaca_available:
                tools.insert(0, toolkit.get_alpaca_data_report)

        if sellthenews_options_available:
            tools.append(toolkit.get_sellthenews_options_data)

        technical_brief_available = toolkit.config["online_tools"] and alpaca_available
        brief_tool_name = "get_trend_brief" if is_trend_horizon else "get_technical_brief"
        indicator_tool_name = (
            "get_stockstats_indicators_report_online"
            if technical_brief_available
            else "get_stockstats_indicators_report"
        )
        evidence_sources = []
        if technical_brief_available:
            evidence_sources.append(
                f"   - `{brief_tool_name}` for compact synthesized confirmation"
            )
        if alpaca_available:
            evidence_sources.append("   - `get_alpaca_data_report` for OHLCV context")
        evidence_sources.append(f"   - `{indicator_tool_name}` for indicator history")
        if sellthenews_options_available:
            evidence_sources.append(
                "   - `get_sellthenews_options_data` for equity options positioning, gamma flip, GEX/pin levels, and expiry risk"
            )

        workflow_intro = (
            "1. **Use the currently available technical tools as your base evidence:**\n"
            + "\n".join(evidence_sources)
            + "\n"
            + point_in_time_source_note(current_date, toolkit.config)
            + "\n"
        )
        if technical_brief_available:
            if is_trend_horizon:
                workflow_step_two = f"""
2. **Call `get_trend_brief`** with the ticker, current date, and horizon='{horizon_context["horizon"]}'.
   You will receive a JSON object focused on {horizon_context["holding_period"]} trend evidence:
   - daily/weekly or weekly/monthly trend structure
   - moving-average slopes and alignment
   - 3M/6M/12M returns and drawdown from 52-week high
   - relative strength vs benchmark
   - trend invalidation level and review cadence
"""
            else:
                workflow_step_two = """
2. **Call `get_technical_brief`** with the ticker and current date.
   You will receive a JSON object with the following pre-analyzed sections for each timeframe:
   - `trend` – direction, strength (ADX), EMA slope, HH/HL, SMA 200 & distance
   - `momentum` – RSI, Stoch RSI (K/D), MACD cross
   - `vwap_state` – above/below VWAP with z-score distance
   - `volatility` – ATR, Bollinger squeeze, Gap %
   - `volume` – Volume trend, MA ratio, OBV slope
   - `market_structure` – BOS / CHOCH, last swing points
   Plus cross-timeframe fields:
   - `key_levels` – Support/Resist (incl. 3M/6M highs), Pivots, Fibs
   - `signal_summary` – classified setup type and confidence
"""
        else:
            workflow_step_two = (
                f"\n2. **`{brief_tool_name}` is unavailable in this run.** "
                "Build the cross-timeframe view from the available price and indicator tools instead.\n"
            )

        if is_trend_horizon:
            iteration_guidance = (
                "\n3. **Actively gather horizon-appropriate evidence before concluding**:\n"
                f"   - Focus on {horizon_context['primary_timeframes']} and {horizon_context['holding_period']} durability.\n"
                "   - Prefer 200D/40W trend, 3M/6M/12M returns, relative strength, drawdown, and invalidation evidence over Stoch RSI/VWAP timing.\n"
                "   - Use short-term indicators only as secondary timing context, not as the core thesis.\n"
                + (
                    "   - If options positioning is available, use it only as a secondary flow/risk overlay after price-trend confirmation.\n"
                    if sellthenews_options_available
                    else ""
                )
            )
        else:
            iteration_guidance = (
            "\n3. **Actively iterate tool calls before concluding**:\n"
            "   - Run at least 3 indicator-history calls across different indicators and at least 2 timeframes when the tool supports it.\n"
            "   - Example flow: momentum (`rsi_14`/`macd`) -> trend (`close_8_ema`, `close_21_ema`, `close_50_sma`) -> volatility/risk (`atr_14`, Bollinger).\n"
            + (
                "   - Cross-check indicator history against price levels from Alpaca.\n"
                if alpaca_available
                else "   - Do not request unavailable Alpaca data; rely on indicator history and explicitly state that limitation.\n"
            )
            + (
                "   - If options positioning is available, call `get_sellthenews_options_data` once with ticker, current date, and greeks='gamma'.\n"
                if sellthenews_options_available
                else ""
            )
            )

        system_intro = load_prompt(
            "analysts/market_intro_with_brief"
            if technical_brief_available
            else "analysts/market_intro_without_brief"
        )
        anchor_guidance = (
            "**Important**: Anchor your thesis in both Alpaca price action and Stockstats indicators."
            if alpaca_available
            else "**Important**: Anchor your thesis in the available Stockstats evidence and explicitly note that Alpaca price data is unavailable."
        )

        system_message = render_prompt(
            "analysts/market_system",
            system_intro=system_intro,
            horizon_agent_context=horizon_agent_context,
            horizon_label=horizon_context["label"],
            holding_period=horizon_context["holding_period"],
            primary_timeframes=horizon_context["primary_timeframes"],
            language_instruction=language_instruction(toolkit.config),
            workflow_intro=workflow_intro,
            workflow_step_two=workflow_step_two,
            iteration_guidance=iteration_guidance,
            anchor_guidance=anchor_guidance,
        )
        asset_context = f"The company we want to look at is {ticker}"

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    load_prompt("shared/analyst_tool_system"),
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)
        prompt = prompt.partial(asset_context=asset_context)

        # Capture the COMPLETE resolved prompt that gets sent to the LLM
        try:
            # Get the formatted messages with all variables resolved
            messages_history = list(state["messages"])
            formatted_messages = prompt.format_messages(messages=messages_history)
            
            # Extract the complete system message (first message)
            if formatted_messages and hasattr(formatted_messages[0], 'content'):
                complete_prompt = formatted_messages[0].content
            else:
                # Fallback: manually construct the complete prompt
                tool_names_str = ", ".join([tool.name for tool in tools])
                complete_prompt = render_prompt(
                    "shared/analyst_tool_system",
                    tool_names=tool_names_str,
                    system_message=system_message,
                    current_date=current_date,
                    asset_context=asset_context,
                )
            
            capture_agent_prompt("market_report", complete_prompt, ticker)
        except Exception as e:
            print(f"[MARKET] Warning: Could not capture complete prompt: {e}")
            # Fallback to system message only
            capture_agent_prompt("market_report", system_message, ticker)

        chain = prompt | (llm.bind_tools(tools) if tools else llm)

        # Copy the incoming conversation history so we can append to it when the model makes tool calls
        messages_history = list(state["messages"])

        # First LLM response
        result = chain.invoke(messages_history)
        max_tool_iterations = int(toolkit.config.get("max_tool_iterations_per_agent", 8))
        max_same_call_repeats = int(toolkit.config.get("max_same_tool_call_repeats", 1))
        tool_call_counts = {}
        tool_result_cache = {}
        iteration_count = 0

        def _execute_tool(tool_name: str, tool_args: dict) -> str:
            tool_fn = next((t for t in tools if t.name == tool_name), None)
            if tool_fn is None:
                tool_result = f"Tool '{tool_name}' not found."
                print(f"[MARKET] ⚠️ {tool_result}")
                return tool_result

            call_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
            call_count = tool_call_counts.get(call_signature, 0) + 1
            tool_call_counts[call_signature] = call_count

            if call_signature in tool_result_cache:
                return tool_result_cache[call_signature]
            if call_count > max_same_call_repeats:
                return (
                    f"Skipped repeated tool call '{tool_name}' with identical arguments "
                    f"after {max_same_call_repeats} execution(s). Reuse previous evidence."
                )
            try:
                # LangChain Tool objects expose `.run` (string IO) as well as `.invoke` (dict/kwarg IO)
                if hasattr(tool_fn, "invoke"):
                    tool_result = tool_fn.invoke(tool_args)
                else:
                    tool_result = tool_fn.run(**tool_args)
                tool_result_cache[call_signature] = str(tool_result)
                return str(tool_result)
            except Exception as tool_err:
                return f"Error running tool '{tool_name}': {str(tool_err)}"

        # Handle iterative tool calls until the model stops requesting them
        while tools and getattr(result, "additional_kwargs", {}).get("tool_calls") and iteration_count < max_tool_iterations:
            iteration_count += 1
            tool_messages = []
            for tool_call in result.additional_kwargs["tool_calls"]:
                # Handle different tool call structures
                if isinstance(tool_call, dict):
                    tool_name = tool_call.get("name") or tool_call.get("function", {}).get("name")
                    tool_args = tool_call.get("args", {}) or tool_call.get("function", {}).get("arguments", {})
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}
                else:
                    # Handle LangChain ToolCall objects
                    tool_name = getattr(tool_call, 'name', None)
                    tool_args = getattr(tool_call, 'args', {})

                tool_result = _execute_tool(tool_name, tool_args)

                # Preserve the original assistant message because DeepSeek thinking
                # mode requires its reasoning_content to be passed back.
                tool_call_id = (
                    tool_call.get("id") or tool_call.get("tool_call_id")
                    if isinstance(tool_call, dict)
                    else getattr(tool_call, "id", None) or getattr(tool_call, "tool_call_id", None)
                )
                tool_msg = ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call_id,
                )
                tool_messages.append(tool_msg)

            messages_history.append(result)
            messages_history.extend(tool_messages)

            # Ask the LLM to continue with the new context
            result = chain.invoke(messages_history)

        if sellthenews_options_available and not any(
            sig.startswith("get_sellthenews_options_data:") for sig in tool_result_cache
        ):
            options_result = _execute_tool(
                "get_sellthenews_options_data",
                {"ticker": ticker, "curr_date": current_date, "greeks": "gamma"},
            )
            messages_history.append(
                AIMessage(
                    content=(
                        "Additional options positioning context fetched because SellTheNews options are enabled "
                        "and the model did not call the options tool before drafting.\n\n"
                        + str(options_result)
                    )
                )
            )
            result = chain.invoke(messages_history)

        if tools and getattr(result, "additional_kwargs", {}).get("tool_calls"):
            result = AIMessage(
                content=(
                    (result.content or "").strip()
                    + f"\n\nTool-loop halted after {max_tool_iterations} iterations to prevent endless retries."
                ).strip()
            )
        
        analysis_content = (result.content or "").strip()
        if not analysis_content:
            analysis_content = (
                "The analyst did not return a complete technical narrative. "
                "State the limitation clearly in the final recommendation."
            )

        # Check if the result already contains FINAL TRANSACTION PROPOSAL
        if "FINAL TRANSACTION PROPOSAL:" not in analysis_content:
            # Create a simple prompt that includes the analysis content directly
            final_prompt = render_prompt(
                "analysts/market_final_recommendation",
                ticker=ticker,
                analysis_content=analysis_content,
            )
            
            # Use a simple chain without tools for the final recommendation
            final_chain = llm
            final_result = final_chain.invoke(final_prompt)
            
            # Combine the analysis with the final proposal
            combined_content = analysis_content + "\n\n" + final_result.content
            result = AIMessage(content=_normalize_market_report_markdown(combined_content))
        else:
            result = AIMessage(content=_normalize_market_report_markdown(analysis_content))

        return {
            "messages": [result],
            "market_report": result.content,
        }

    return market_analyst_node

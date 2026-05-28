import time
import json
from ..schemas import RiskDecision, render_risk_decision
from ..utils.agent_trading_modes import (
    ensure_final_transaction_proposal,
    get_agent_horizon_context,
    get_trading_mode_context,
    get_agent_specific_context,
    get_horizon_context,
    extract_recommendation,
    validate_recommendation,
)
from ..utils.language import output_language
from ..utils.memory import TradingMemoryLog
from ..utils.report_context import (
    get_agent_context_bundle,
    build_debate_digest,
)
from ..utils.structured import bind_structured, invoke_structured_or_freetext
from tradingagents.dataflows.alpaca_utils import AlpacaUtils
from tradingagents.trade_lifecycle import build_plan_from_final_state
from tradingagents.portfolio import (
    build_decision_policy_context,
    build_portfolio_policy_context,
    build_sizing_guidance_context,
    build_theme_basket_context,
    evaluate_decision_policy,
    render_decision_policy_result,
)
from tradingagents.prompts import render_prompt

# Import prompt capture utility
try:
    from webui.utils.prompt_capture import capture_agent_prompt
except ImportError:
    # Fallback for when webui is not available
    def capture_agent_prompt(report_type, prompt_content, symbol=None):
        pass


def validate_risk_decision_text(
    response_content: str,
    *,
    trading_mode: str,
    current_position: str,
    horizon_context: dict,
    config: dict | None = None,
) -> tuple[str, str]:
    """Apply deterministic execution-safety corrections after the risk judge."""
    default_action = "NEUTRAL" if trading_mode == "trading" else "HOLD"
    parsed_action = extract_recommendation(response_content, trading_mode)
    notes: list[str] = []

    if not parsed_action or not validate_recommendation(parsed_action, trading_mode):
        parsed_action = default_action
        notes.append(f"unparseable or invalid action downgraded to {default_action}")

    if (
        trading_mode == "investment"
        and parsed_action == "SELL"
        and str(current_position or "NEUTRAL").upper() == "NEUTRAL"
    ):
        parsed_action = "HOLD"
        notes.append("long-only flat SELL downgraded to HOLD")

    if (config or {}).get("decision_policy_enabled", True):
        policy_result = evaluate_decision_policy(
            config=config,
            horizon=horizon_context.get("horizon"),
            proposed_action=parsed_action,
            evidence_text=response_content,
        )
        if policy_result.validator_note:
            parsed_action = policy_result.recommended_action
            notes.append(policy_result.validator_note)
            response_content = (
                f"{response_content.rstrip()}\n\n"
                f"Decision Policy Result:\n{render_decision_policy_result(policy_result)}"
            )

    lowered = str(response_content or "").lower()
    if horizon_context.get("research_only") and any(
        phrase in lowered
        for phrase in (
            "live order",
            "place order",
            "send order",
            "execute now",
            "open/add",
            "open order",
        )
    ):
        notes.append("research-only horizon: no live Alpaca order should be placed")

    final_content = ensure_final_transaction_proposal(
        response_content,
        parsed_action,
        trading_mode,
    )

    expected_final = f"FINAL TRANSACTION PROPOSAL: **{parsed_action}**"
    final_lines = [
        line
        for line in final_content.splitlines()
        if "FINAL TRANSACTION PROPOSAL:" in line.upper()
    ]
    if len(final_lines) != 1 or final_lines[-1].strip() != expected_final:
        final_content = "\n".join(
            line
            for line in final_content.splitlines()
            if "FINAL TRANSACTION PROPOSAL:" not in line.upper()
        ).rstrip()
        final_content = ensure_final_transaction_proposal(
            final_content,
            parsed_action,
            trading_mode,
        )
        notes.append("final proposal normalized to validated action")

    if notes:
        final_content = f"{final_content.rstrip()}\n\nValidator Note: {'; '.join(notes)}."

    return final_content, parsed_action


def create_risk_manager(llm, memory, config=None):
    structured_llm = bind_structured(llm, RiskDecision, "Risk Manager")
    decision_log = TradingMemoryLog(config)

    def risk_manager_node(state) -> dict:

        company_name = state["company_of_interest"]

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        trader_plan = state["investment_plan"]

        # Get trading mode from config
        allow_shorts = config.get("allow_shorts", False) if config else False

        # Determine live position from Alpaca
        current_position = AlpacaUtils.get_current_position_state(company_name)
        state["current_position"] = current_position

        # ---------------------------------------------------------
        # NEW: Fetch richer live account & position metrics from Alpaca
        # ---------------------------------------------------------
        positions_data = AlpacaUtils.get_positions_data()
        account_info = AlpacaUtils.get_account_info()

        # Build summary for specific symbol
        position_stats_desc = ""
        symbol_key = company_name.upper().replace("/", "")
        for pos in positions_data:
            if pos["Symbol"].upper() == symbol_key:
                qty = pos["Qty"]
                avg_entry = pos["Avg Entry"]
                today_pl_dollars = pos["Today's P/L ($)"]
                today_pl_percent = pos["Today's P/L (%)"]
                total_pl_dollars = pos["Total P/L ($)"]
                total_pl_percent = pos["Total P/L (%)"]

                position_stats_desc = (
                    f"Position Details for {company_name}:\n"
                    f"- Quantity: {qty}\n"
                    f"- Average Entry Price: {avg_entry}\n"
                    f"- Today's P/L: {today_pl_dollars} ({today_pl_percent})\n"
                    f"- Total P/L: {total_pl_dollars} ({total_pl_percent})"
                )
                break
        if not position_stats_desc:
            position_stats_desc = "No open position details available for this symbol."

        buying_power = account_info.get("buying_power", 0.0)
        cash = account_info.get("cash", 0.0)
        equity = account_info.get("equity", 0.0)
        daily_change_dollars = account_info.get("daily_change_dollars", 0.0)
        daily_change_percent = account_info.get("daily_change_percent", 0.0)
        account_status_desc = (
            "Account Status:\n"
            f"- Account Equity / NAV: ${equity:,.2f}\n"
            f"- Buying Power: ${buying_power:,.2f}\n"
            f"- Cash: ${cash:,.2f}\n"
            f"- Daily Change: ${daily_change_dollars:,.2f} ({daily_change_percent:.2f}%)"
        )
        open_pos_desc = (
            f"We currently have an open {current_position} position in {company_name}."
            if current_position != "NEUTRAL"
            else f"We do not have any open position in {company_name}."
        )
        
        # Get centralized trading mode context
        trading_context = get_trading_mode_context(config, current_position)
        horizon_context = get_horizon_context(config)
        portfolio_policy_context = build_portfolio_policy_context(config)
        sizing_guidance_context = build_sizing_guidance_context(config)
        decision_policy_context = build_decision_policy_context(config, horizon_context["horizon"])
        theme_basket_context = build_theme_basket_context(company_name, positions_data, account_info, config)
        # ---------------------------------------------------------
        # END NEW BLOCK
        # ---------------------------------------------------------

        agent_context = get_agent_specific_context("manager", trading_context)
        horizon_agent_context = get_agent_horizon_context("risk_mgmt", horizon_context)
        
        # Get mode-specific terms for the prompt
        actions = trading_context["actions"]
        mode_name = trading_context["mode_name"]
        decision_format = trading_context["decision_format"]
        final_format = trading_context["final_format"]
        language = output_language(config)
        context_bundle = get_agent_context_bundle(
            state,
            agent_role="managers/risk_manager",
            objective=(
                f"Judge risk debate and finalize risk-adjusted trade decision for {company_name}. "
                f"Horizon: {horizon_context['label']} ({horizon_context['holding_period']}). "
                f"Trader plan: {trader_plan}"
            ),
            config=config,
        )
        claim_matrix = context_bundle.get("decision_claim_matrix", "")
        risk_debate_digest = build_debate_digest(risk_debate_state, "risk", config=config)
        all_reports_text = context_bundle.get("all_reports_text", "")

        curr_situation = context_bundle["memory_context"]
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"
        decision_memory_str = decision_log.get_past_context(
            company_name,
            horizon=horizon_context["horizon"],
        )

        prompt = render_prompt(
            "managers/risk_manager",
            agent_context=agent_context,
            horizon_agent_context=horizon_agent_context,
            horizon_label=horizon_context["label"],
            holding_period=horizon_context["holding_period"],
            primary_timeframes=horizon_context["primary_timeframes"],
            research_only_note=(
                "Trend-horizon execution is research-only unless explicitly enabled."
                if horizon_context["research_only"]
                else "Execution may follow the normal order setting when enabled."
            ),
            decision_format=decision_format,
            open_pos_desc=open_pos_desc,
            position_stats_desc=position_stats_desc,
            account_status_desc=account_status_desc,
            portfolio_policy_context=portfolio_policy_context,
            decision_policy_context=decision_policy_context,
            theme_basket_context=theme_basket_context,
            sizing_guidance_context=sizing_guidance_context,
            trader_plan=trader_plan,
            claim_matrix=claim_matrix,
            all_reports_text=all_reports_text,
            risk_debate_digest=risk_debate_digest,
            history=history,
            past_memory_str=past_memory_str,
            decision_memory_str=decision_memory_str,
            actions=actions,
            final_format=final_format,
            output_language=language,
        )

        # Capture the COMPLETE prompt that gets sent to the LLM
        capture_agent_prompt("final_trade_decision", prompt, company_name)

        response_content = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            lambda decision: render_risk_decision(decision, language),
            "Risk Manager",
        )

        # Extract the recommendation from the response
        trading_mode = trading_context["mode"]
        extracted_recommendation = extract_recommendation(response_content, trading_mode)
        if not extracted_recommendation:
            extracted_recommendation = "NEUTRAL" if trading_mode == "trading" else "HOLD"

        prevalidated_decision_content = ensure_final_transaction_proposal(
            response_content, extracted_recommendation, trading_mode
        )
        final_decision_content, extracted_recommendation = validate_risk_decision_text(
            prevalidated_decision_content,
            trading_mode=trading_mode,
            current_position=current_position,
            horizon_context=horizon_context,
            config=config,
        )

        new_risk_debate_state = {
            "judge_decision": final_decision_content,
            "history": risk_debate_state["history"],
            "risky_history": risk_debate_state["risky_history"],
            "safe_history": risk_debate_state["safe_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "risky_messages": risk_debate_state.get("risky_messages", []),
            "safe_messages": risk_debate_state.get("safe_messages", []),
            "neutral_messages": risk_debate_state.get("neutral_messages", []),
            "latest_speaker": "Judge",
            "phase": risk_debate_state.get("phase", "rebuttal"),
            "rebuttal_rounds_completed": risk_debate_state.get("rebuttal_rounds_completed", 0),
            "current_risky_response": risk_debate_state["current_risky_response"],
            "current_safe_response": risk_debate_state["current_safe_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        result_state = {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_decision_content,
            "trading_mode": trading_mode,
            "trading_horizon": horizon_context["horizon"],
            "current_position": current_position,
            "recommended_action": extracted_recommendation,
        }
        try:
            plan = build_plan_from_final_state(
                {
                    **state,
                    **result_state,
                    "company_of_interest": company_name,
                },
                config=config,
            )
            result_state["conditional_trade_plan"] = plan.model_dump(mode="json") if plan else {}
        except Exception as exc:
            print(f"[TRADE_PLAN] Warning: could not build conditional trade plan draft: {exc}")
            result_state["conditional_trade_plan"] = {}
        return result_state

    return risk_manager_node

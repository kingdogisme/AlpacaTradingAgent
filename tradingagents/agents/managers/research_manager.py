import time
import json
from ..utils.report_context import (
    get_agent_context_bundle,
    build_debate_digest,
)
from ..schemas import ResearchPlan, render_research_plan
from ..utils.agent_trading_modes import (
    ensure_final_transaction_proposal,
    extract_recommendation,
    get_agent_horizon_context,
    get_horizon_context,
    get_trading_mode_context,
)
from ..utils.language import output_language
from ..utils.memory import TradingMemoryLog
from ..utils.structured import bind_structured, invoke_structured_or_freetext
from tradingagents.prompts import render_prompt

# Import prompt capture utility
try:
    from webui.utils.prompt_capture import capture_agent_prompt
except ImportError:
    # Fallback for when webui is not available
    def capture_agent_prompt(report_type, prompt_content, symbol=None):
        pass


def create_research_manager(llm, memory, config=None):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")
    decision_log = TradingMemoryLog(config)

    def research_manager_node(state) -> dict:
        history = state["investment_debate_state"].get("history", "")
        investment_debate_state = state["investment_debate_state"]
        trading_context = get_trading_mode_context(config)
        horizon_context = get_horizon_context(config)
        horizon_agent_context = get_agent_horizon_context("trader", horizon_context)
        actions = trading_context["actions"]
        trading_mode = trading_context["mode"]
        final_format = trading_context["final_format"]
        ticker = state.get("company_of_interest", "")
        language = output_language(config)

        context_bundle = get_agent_context_bundle(
            state,
            agent_role="managers/research_manager",
            objective=(
                f"Adjudicate bull/bear debate for {state.get('company_of_interest', '')} "
                "and produce a decisive investment plan."
            ),
        )
        claim_matrix = context_bundle.get("decision_claim_matrix", "")
        debate_digest = build_debate_digest(investment_debate_state, "investment")
        all_reports_text = context_bundle.get("all_reports_text", "")

        curr_situation = context_bundle["memory_context"]
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"
        decision_memory_str = decision_log.get_past_context(
            ticker,
            horizon=horizon_context["horizon"],
        )

        prompt = render_prompt(
            "managers/research_manager",
            actions=actions,
            horizon_agent_context=horizon_agent_context,
            horizon_label=horizon_context["label"],
            holding_period=horizon_context["holding_period"],
            primary_timeframes=horizon_context["primary_timeframes"],
            research_only_note=(
                "Trend-horizon execution is research-only unless explicitly enabled."
                if horizon_context["research_only"]
                else "Execution may follow the normal order setting when enabled."
            ),
            claim_matrix=claim_matrix,
            all_reports_text=all_reports_text,
            debate_digest=debate_digest,
            past_memory_str=past_memory_str,
            decision_memory_str=decision_memory_str,
            history=history,
            final_format=final_format,
            output_language=language,
        )

        # Capture the COMPLETE prompt that gets sent to the LLM
        capture_agent_prompt("research_manager_report", prompt, ticker)

        response_content = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )
        extracted_recommendation = extract_recommendation(response_content, trading_mode)
        if extracted_recommendation:
            response_content = ensure_final_transaction_proposal(
                response_content, extracted_recommendation, trading_mode
            )

        new_investment_debate_state = {
            "judge_decision": response_content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "bull_messages": investment_debate_state.get("bull_messages", []),
            "bear_messages": investment_debate_state.get("bear_messages", []),
            "current_response": response_content,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": response_content,
        }

    return research_manager_node

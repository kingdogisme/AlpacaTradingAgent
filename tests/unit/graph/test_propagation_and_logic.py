from __future__ import annotations

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator


class Message:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls or []


def test_propagator_initializes_full_agent_state():
    state = Propagator(max_recur_limit=123).create_initial_state("BTC/USD", "2026-01-02")

    assert state["company_of_interest"] == "BTC/USD"
    assert state["trade_date"] == "2026-01-02"
    assert state["macro_report"] == ""
    assert state["report_context"] == {}
    assert state["investment_debate_state"]["bull_messages"] == []
    assert state["risk_debate_state"]["latest_speaker"] == "Risky"
    assert state["risk_debate_state"]["phase"] == "opening"
    assert state["risk_debate_state"]["rebuttal_rounds_completed"] == 0
    assert state["risk_debate_state"]["neutral_messages"] == []


def test_graph_args_include_configured_recursion_limit():
    args = Propagator(max_recur_limit=77).get_graph_args()

    assert args["stream_mode"] == "values"
    assert args["config"]["recursion_limit"] == 77


def test_conditional_logic_routes_tool_calls_and_clear_paths():
    logic = ConditionalLogic()

    assert logic.should_continue_market({"messages": [Message(tool_calls=[{"name": "tool"}])]} ) == "tools_market"
    assert logic.should_continue_market({"messages": [Message()]}) == "Msg Clear Market"
    assert logic.should_continue_macro({"messages": [Message(tool_calls=[{"name": "tool"}])]} ) == "tools_macro"
    assert logic.should_continue_macro({"messages": [Message()]}) == "Msg Clear Macro"


def test_conditional_logic_enforces_debate_round_boundaries():
    logic = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)

    assert logic.should_continue_debate(
        {"investment_debate_state": {"count": 2, "current_response": "Bull Analyst: case"}}
    ) == "Research Manager"
    assert logic.should_continue_debate(
        {"investment_debate_state": {"count": 1, "current_response": "Bull Analyst: case"}}
    ) == "Bear Researcher"
    assert logic.should_continue_debate(
        {"investment_debate_state": {"count": 1, "current_response": "Bear Analyst: case"}}
    ) == "Bull Researcher"

    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 6, "latest_speaker": "Neutral", "phase": "rebuttal", "rebuttal_rounds_completed": 1}}
    ) == "Risk Judge"
    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 1, "latest_speaker": "Risky", "phase": "rebuttal", "rebuttal_rounds_completed": 1}}
    ) == "Safe Analyst"
    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 1, "latest_speaker": "Safe", "phase": "rebuttal", "rebuttal_rounds_completed": 1}}
    ) == "Neutral Analyst"


def test_parallel_risk_opening_requires_full_rebuttal_cycle():
    logic = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)

    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 3, "latest_speaker": "Opening", "phase": "rebuttal", "rebuttal_rounds_completed": 0}}
    ) == "Risky Analyst"
    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 4, "latest_speaker": "Risky", "phase": "rebuttal", "rebuttal_rounds_completed": 0}}
    ) == "Safe Analyst"
    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 5, "latest_speaker": "Safe", "phase": "rebuttal", "rebuttal_rounds_completed": 0}}
    ) == "Neutral Analyst"
    assert logic.should_continue_risk_analysis(
        {"risk_debate_state": {"count": 6, "latest_speaker": "Neutral", "phase": "rebuttal", "rebuttal_rounds_completed": 1}}
    ) == "Risk Judge"

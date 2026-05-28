from __future__ import annotations

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.risk_mgmt.aggresive_debator import create_risky_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_safe_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator


class PlainLLM:
    def __init__(self, content: str):
        self.content = content
        self.last_prompt = None

    def invoke(self, _prompt):
        self.last_prompt = _prompt
        return type("Message", (), {"content": self.content})()


class EmptyMemory:
    def get_memories(self, _current_situation, n_matches=1):
        return []


def _state() -> dict:
    return {
        "company_of_interest": "AAPL",
        "market_report": "Market evidence.",
        "sentiment_report": "Sentiment evidence.",
        "news_report": "News evidence.",
        "fundamentals_report": "Fundamental evidence.",
        "macro_report": "Macro evidence.",
        "report_context": {},
        "investment_debate_state": {
            "history": "",
            "current_response": "",
            "bull_history": "",
            "bear_history": "",
            "bull_messages": [],
            "bear_messages": [],
            "judge_decision": "",
            "count": 0,
        },
        "trader_investment_plan": "Trader plan.\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "current_position": "NEUTRAL",
        "risk_debate_state": {
            "history": "",
            "latest_speaker": "Risky",
            "phase": "opening",
            "rebuttal_rounds_completed": 0,
            "risky_history": "",
            "safe_history": "",
            "neutral_history": "",
            "risky_messages": [],
            "safe_messages": [],
            "neutral_messages": [],
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }


def test_bull_and_bear_researchers_update_debate_state(isolated_config):
    state = _state()
    bull = create_bull_researcher(PlainLLM("Bull case."), EmptyMemory(), isolated_config)
    bear = create_bear_researcher(PlainLLM("Bear case."), EmptyMemory(), isolated_config)

    bull_state = bull(state)["investment_debate_state"]
    state["investment_debate_state"] = bull_state
    bear_state = bear(state)["investment_debate_state"]

    assert bull_state["count"] == 1
    assert bull_state["current_response"].startswith("Bull Analyst:")
    assert bear_state["count"] == 2
    assert bear_state["current_response"].startswith("Bear Analyst:")
    assert len(bear_state["bull_messages"]) == 1
    assert len(bear_state["bear_messages"]) == 1


def test_risk_debators_update_speaker_specific_state(isolated_config):
    state = _state()

    risky = create_risky_debator(PlainLLM("Aggressive risk."), isolated_config)
    safe = create_safe_debator(PlainLLM("Conservative risk."), isolated_config)
    neutral = create_neutral_debator(PlainLLM("Balanced risk."), isolated_config)

    risk_state = risky(state)["risk_debate_state"]
    state["risk_debate_state"] = risk_state
    risk_state = safe(state)["risk_debate_state"]
    state["risk_debate_state"] = risk_state
    risk_state = neutral(state)["risk_debate_state"]

    assert risk_state["count"] == 3
    assert risk_state["latest_speaker"] == "Neutral"
    assert risk_state["current_risky_response"].startswith("Risky Analyst:")
    assert risk_state["current_safe_response"].startswith("Safe Analyst:")
    assert risk_state["current_neutral_response"].startswith("Neutral Analyst:")
    assert len(risk_state["risky_messages"]) == 1
    assert len(risk_state["safe_messages"]) == 1
    assert len(risk_state["neutral_messages"]) == 1
    assert risk_state["phase"] == "rebuttal"
    assert risk_state["rebuttal_rounds_completed"] == 1


def test_risk_opening_and_rebuttal_prompts_include_phase(isolated_config):
    state = _state()
    llm = PlainLLM("Aggressive opening.")
    risky = create_risky_debator(llm, isolated_config)

    opening_state = risky(state)["risk_debate_state"]
    assert "Debate phase: opening" in llm.last_prompt
    assert "standalone opening statement only" in llm.last_prompt

    state["risk_debate_state"] = {
        **opening_state,
        "phase": "rebuttal",
        "current_safe_response": "Safe Analyst: opening caution.",
        "current_neutral_response": "Neutral Analyst: opening balance.",
    }
    llm.content = "Aggressive rebuttal."
    risky(state)

    assert "Debate phase: rebuttal" in llm.last_prompt
    assert "Safe Analyst: opening caution." in llm.last_prompt
    assert "Neutral Analyst: opening balance." in llm.last_prompt

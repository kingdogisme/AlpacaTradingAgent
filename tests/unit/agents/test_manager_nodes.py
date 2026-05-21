from __future__ import annotations

from unittest.mock import patch

from tradingagents.agents.schemas import ExecutableAction, RiskDecision, TraderProposal
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.managers.risk_manager import create_risk_manager
from tradingagents.agents.trader.trader import create_trader


class PlainLLM:
    def __init__(self, content: str):
        self.content = content
        self.prompts = []

    def with_structured_output(self, _schema):
        raise NotImplementedError("structured unavailable in this test")

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return type("Message", (), {"content": self.content})()


class EmptyMemory:
    def get_memories(self, _current_situation, n_matches=1):
        return []


class StructuredLLM:
    def __init__(self, parsed):
        self.parsed = parsed

    def bind_tools(self, _tools, **_kwargs):
        return self

    def invoke(self, _prompt, *args, **kwargs):
        return self.parsed


class DirectStructuredLLM:
    def __init__(self, parsed):
        self.parsed = parsed

    def invoke(self, _prompt, *args, **kwargs):
        return self.parsed

    def with_structured_output(self, _schema):
        return self


def _base_state() -> dict:
    return {
        "company_of_interest": "AAPL",
        "trade_date": "2026-01-02",
        "market_report": "Market report with support at 190 and RSI 61.",
        "sentiment_report": "Sentiment report with mixed retail positioning.",
        "news_report": "News report with product launch catalyst.",
        "fundamentals_report": "Fundamentals report with revenue growth.",
        "macro_report": "Macro report with yield pressure.",
        "report_context": {},
        "investment_debate_state": {
            "history": "Bull and bear debate.",
            "current_response": "Bear Analyst: valuation risk.",
            "bull_history": "Bull Analyst: upside.",
            "bear_history": "Bear Analyst: downside.",
            "bull_messages": ["Bull Analyst: upside."],
            "bear_messages": ["Bear Analyst: downside."],
            "judge_decision": "",
            "count": 2,
        },
        "investment_plan": "Research plan.\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "trader_investment_plan": "Trader plan.\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "risk_debate_state": {
            "history": "Risk debate.",
            "latest_speaker": "Neutral",
            "risky_history": "Risky Analyst: upside.",
            "safe_history": "Safe Analyst: caution.",
            "neutral_history": "Neutral Analyst: balanced.",
            "risky_messages": ["Risky Analyst: upside."],
            "safe_messages": ["Safe Analyst: caution."],
            "neutral_messages": ["Neutral Analyst: balanced."],
            "current_risky_response": "Risky Analyst: upside.",
            "current_safe_response": "Safe Analyst: caution.",
            "current_neutral_response": "Neutral Analyst: balanced.",
            "judge_decision": "",
            "count": 3,
        },
    }


def test_research_manager_preserves_executable_action_over_advisory_rating(isolated_config):
    llm = PlainLLM("**Advisory Rating**: Sell\n\nEvidence body.\nFINAL TRANSACTION PROPOSAL: **BUY**")
    node = create_research_manager(llm, EmptyMemory(), isolated_config)

    result = node(_base_state())

    assert result["investment_plan"].endswith("FINAL TRANSACTION PROPOSAL: **BUY**")
    assert result["investment_debate_state"]["judge_decision"] == result["investment_plan"]


def test_trader_injects_position_context_and_adds_missing_final_line(isolated_config):
    llm = PlainLLM("Trader evidence supports staying patient.")
    node = create_trader(llm, EmptyMemory(), isolated_config)

    with patch("tradingagents.agents.trader.trader.AlpacaUtils.get_current_position_state", return_value="NEUTRAL"), patch(
        "tradingagents.agents.trader.trader.AlpacaUtils.get_positions_data", return_value=[]
    ), patch(
        "tradingagents.agents.trader.trader.AlpacaUtils.get_account_info",
        return_value={"equity": 2500, "buying_power": 1000, "cash": 500},
    ):
        result = node(_base_state())

    assert result["trader_investment_plan"].endswith("FINAL TRANSACTION PROPOSAL: **HOLD**")
    assert result["recommended_action"] == "HOLD"
    assert result["current_position"] == "NEUTRAL"
    assert "Account Status" in str(llm.prompts[0])
    assert "Account Equity / NAV: $2,500.00" in str(llm.prompts[0])


def test_trader_structured_output_uses_configured_language(isolated_config):
    isolated_config["output_language"] = "zh-CN"
    llm = DirectStructuredLLM(
        TraderProposal(
            action=ExecutableAction.HOLD,
            confidence="medium",
            reasoning="趋势未坏，但当前缺少确认。",
        )
    )
    node = create_trader(llm, EmptyMemory(), isolated_config)

    with patch("tradingagents.agents.trader.trader.AlpacaUtils.get_current_position_state", return_value="NEUTRAL"), patch(
        "tradingagents.agents.trader.trader.AlpacaUtils.get_positions_data", return_value=[]
    ), patch("tradingagents.agents.trader.trader.AlpacaUtils.get_account_info", return_value={"buying_power": 1000, "cash": 500}):
        result = node(_base_state())

    assert "**操作**: HOLD" in result["trader_investment_plan"]
    assert "**判断依据**: 趋势未坏，但当前缺少确认。" in result["trader_investment_plan"]
    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in result["trader_investment_plan"]


def test_risk_manager_outputs_final_executable_action_and_state(isolated_config):
    llm = PlainLLM("Risk review says avoid new exposure.\nFINAL TRANSACTION PROPOSAL: **HOLD**")
    node = create_risk_manager(llm, EmptyMemory(), isolated_config)

    with patch("tradingagents.agents.managers.risk_manager.AlpacaUtils.get_current_position_state", return_value="LONG"), patch(
        "tradingagents.agents.managers.risk_manager.AlpacaUtils.get_positions_data", return_value=[]
    ), patch(
        "tradingagents.agents.managers.risk_manager.AlpacaUtils.get_account_info",
        return_value={"equity": 2500, "buying_power": 1000, "cash": 500},
    ):
        result = node(_base_state())

    assert result["final_trade_decision"].endswith("FINAL TRANSACTION PROPOSAL: **HOLD**")
    assert result["recommended_action"] == "HOLD"
    assert result["risk_debate_state"]["latest_speaker"] == "Judge"
    assert result["current_position"] == "LONG"
    assert "Account Equity / NAV: $2,500.00" in str(llm.prompts[0])


def test_risk_manager_structured_output_uses_configured_language(isolated_config):
    isolated_config["output_language"] = "zh-CN"
    llm = DirectStructuredLLM(
        RiskDecision(
            action=ExecutableAction.HOLD,
            confidence="medium",
            risk_rationale="没有现仓，等待确认更优。",
            required_controls="突破确认后再分批建仓。",
            user_recommendation="保留观察名单，等待突破确认。",
            alpaca_action_plan="HOLD：当前不发送订单。",
        )
    )
    node = create_risk_manager(llm, EmptyMemory(), isolated_config)

    with patch("tradingagents.agents.managers.risk_manager.AlpacaUtils.get_current_position_state", return_value="NEUTRAL"), patch(
        "tradingagents.agents.managers.risk_manager.AlpacaUtils.get_positions_data", return_value=[]
    ), patch("tradingagents.agents.managers.risk_manager.AlpacaUtils.get_account_info", return_value={"buying_power": 1000, "cash": 500}):
        result = node(_base_state())

    assert "**操作**: HOLD" in result["final_trade_decision"]
    assert "**给用户的操作建议**: 保留观察名单，等待突破确认。" in result["final_trade_decision"]
    assert "**给 Alpaca 的直接动作**: HOLD：当前不发送订单。" in result["final_trade_decision"]
    assert "**风险理由**: 没有现仓，等待确认更优。" in result["final_trade_decision"]
    assert "**必要风控**: 突破确认后再分批建仓。" in result["final_trade_decision"]
    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in result["final_trade_decision"]

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.analysts.macro_analyst import create_macro_analyst
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.social_media_analyst import create_social_media_analyst


class Tool:
    def __init__(self, name: str):
        self.name = name


class CapturingLLM:
    def __init__(self, content: str | list[str] = "Analyst report.\nFINAL TRANSACTION PROPOSAL: **HOLD**"):
        self.responses = [content] if isinstance(content, str) else list(content)
        self.prompts = []
        self.bound_tool_names = []

    def _message(self, prompt):
        self.prompts.append(prompt)
        content = self.responses.pop(0) if self.responses else "Analyst report.\nFINAL TRANSACTION PROPOSAL: **HOLD**"
        return AIMessage(content=content)

    def bind_tools(self, tools):
        self.bound_tool_names.append([tool.name for tool in tools])
        return RunnableLambda(lambda _messages: self._message(_messages))

    def invoke(self, prompt):
        return self._message(prompt)


class FakeToolkit:
    def __init__(
        self,
        config=None,
        *,
        alpaca=True,
        openai=True,
        finnhub=True,
        coindesk=True,
        simfin=True,
        fred=True,
    ):
        self.config = {
            "online_tools": True,
            "trading_horizon": "swing",
            "max_tool_iterations_per_agent": 1,
            "max_same_tool_call_repeats": 1,
            **(config or {}),
        }
        self._alpaca = alpaca
        self._openai = openai
        self._finnhub = finnhub
        self._coindesk = coindesk
        self._simfin = simfin
        self._fred = fred
        for name in (
            "get_technical_brief",
            "get_trend_brief",
            "get_alpaca_data_report",
            "get_stockstats_indicators_report_online",
            "get_stockstats_indicators_report",
            "get_google_news",
            "get_global_news_openai",
            "get_finnhub_news_recent",
            "get_coindesk_news",
            "get_stock_news_openai",
            "get_reddit_stock_info",
            "get_reddit_news",
            "get_fundamentals_openai",
            "get_defillama_fundamentals",
            "get_finnhub_company_insider_sentiment",
            "get_finnhub_company_insider_transactions",
            "get_simfin_balance_sheet",
            "get_simfin_cashflow",
            "get_simfin_income_stmt",
            "get_macro_analysis",
            "get_economic_indicators",
            "get_yield_curve_analysis",
            "get_macro_news_openai",
        ):
            setattr(self, name, Tool(name))

    def has_alpaca_credentials(self):
        return self._alpaca

    def has_openai_web_search(self):
        return self._openai

    def has_finnhub(self):
        return self._finnhub

    def has_coindesk(self):
        return self._coindesk

    def has_simfin_data(self):
        return self._simfin

    def has_fred(self):
        return self._fred


def test_market_analyst_uses_technical_brief_for_online_swing_with_alpaca():
    llm = CapturingLLM()
    node = create_market_analyst(llm, FakeToolkit())

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert result["market_report"].endswith("FINAL TRANSACTION PROPOSAL: **HOLD**")
    assert llm.bound_tool_names[-1] == [
        "get_technical_brief",
        "get_alpaca_data_report",
        "get_stockstats_indicators_report_online",
    ]


def test_market_analyst_uses_offline_stockstats_without_alpaca_credentials():
    llm = CapturingLLM()
    node = create_market_analyst(llm, FakeToolkit(alpaca=False))

    node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert llm.bound_tool_names[-1] == ["get_stockstats_indicators_report"]


def test_market_analyst_uses_trend_brief_for_position_horizon():
    llm = CapturingLLM()
    toolkit = FakeToolkit(config={"trading_horizon": "position"})
    node = create_market_analyst(llm, toolkit)

    node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert llm.bound_tool_names[-1][0] == "get_trend_brief"


def test_news_analyst_routes_crypto_to_coindesk_and_stock_to_finnhub():
    stock_llm = CapturingLLM()
    crypto_llm = CapturingLLM()

    stock_node = create_news_analyst(stock_llm, FakeToolkit(config={"news_global_openai_enabled": False}))
    crypto_node = create_news_analyst(crypto_llm, FakeToolkit(config={"news_global_openai_enabled": False}))

    stock_node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})
    crypto_node({"trade_date": "2026-01-02", "company_of_interest": "BTC/USD", "messages": []})

    assert "get_finnhub_news_recent" in stock_llm.bound_tool_names[-1]
    assert "get_coindesk_news" not in stock_llm.bound_tool_names[-1]
    assert "get_coindesk_news" in crypto_llm.bound_tool_names[-1]
    assert "get_finnhub_news_recent" not in crypto_llm.bound_tool_names[-1]


def test_social_media_analyst_writes_sentiment_report_and_appends_final_proposal():
    llm = CapturingLLM(["Social analysis body.", "FINAL TRANSACTION PROPOSAL: **BUY**"])
    node = create_social_media_analyst(llm, FakeToolkit())

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert "Social analysis body." in result["sentiment_report"]
    assert "FINAL TRANSACTION PROPOSAL: **BUY**" in result["sentiment_report"]
    assert "get_stock_news_openai" in llm.bound_tool_names[-1]
    assert "get_reddit_stock_info" in llm.bound_tool_names[-1]


def test_fundamentals_analyst_writes_report_and_routes_crypto_to_defillama():
    llm = CapturingLLM(["Fundamentals analysis body.", "FINAL TRANSACTION PROPOSAL: **HOLD**"])
    node = create_fundamentals_analyst(llm, FakeToolkit())

    result = node({"trade_date": "2026-01-02", "company_of_interest": "BTC/USD", "messages": []})

    assert "Fundamentals analysis body." in result["fundamentals_report"]
    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in result["fundamentals_report"]
    assert "get_defillama_fundamentals" in llm.bound_tool_names[-1]
    assert "get_finnhub_company_insider_sentiment" not in llm.bound_tool_names[-1]


def test_macro_analyst_writes_report_and_appends_final_proposal():
    llm = CapturingLLM(["Macro analysis body.", "FINAL TRANSACTION PROPOSAL: **SELL**"])
    node = create_macro_analyst(llm, FakeToolkit())

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert "Macro analysis body." in result["macro_report"]
    assert "FINAL TRANSACTION PROPOSAL: **SELL**" in result["macro_report"]
    assert llm.bound_tool_names[-1] == [
        "get_macro_analysis",
        "get_economic_indicators",
        "get_yield_curve_analysis",
        "get_macro_news_openai",
    ]

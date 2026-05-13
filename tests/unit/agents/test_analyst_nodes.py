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


class ToolRoundTripLLM:
    def __init__(self):
        self.calls = []
        self.bound_tool_names = []

    def bind_tools(self, tools):
        self.bound_tool_names.append([tool.name for tool in tools])

        def _invoke(messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return AIMessage(
                    content="",
                    additional_kwargs={
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_technical_brief",
                                    "arguments": "{}",
                                },
                            }
                        ],
                        "reasoning_content": "reason before tool",
                    },
                )
            return AIMessage(
                content="Technical analysis complete.\nFINAL TRANSACTION PROPOSAL: **HOLD**"
            )

        return RunnableLambda(_invoke)

    def invoke(self, prompt):
        self.calls.append(prompt)
        return AIMessage(content="FINAL TRANSACTION PROPOSAL: **HOLD**")


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
        alpha_vantage=True,
    ):
        self.config = {
            "online_tools": True,
            "trading_horizon": "swing",
            "max_tool_iterations_per_agent": 1,
            "max_same_tool_call_repeats": 1,
            "social_openai_stock_news_enabled": True,
            "sellthenews_options_enabled": False,
            **(config or {}),
        }
        self._alpaca = alpaca
        self._openai = openai
        self._finnhub = finnhub
        self._coindesk = coindesk
        self._simfin = simfin
        self._fred = fred
        self._alpha_vantage = alpha_vantage
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
            "get_sellthenews_stock_news",
            "get_sellthenews_options_data",
            "get_stock_news_openai",
            "get_reddit_stock_info",
            "get_reddit_news",
            "get_sellthenews_social_sentiment",
            "get_fundamentals_openai",
            "get_alpha_vantage_fundamentals",
            "get_defillama_fundamentals",
            "get_finnhub_company_fundamentals",
            "get_finnhub_company_insider_sentiment",
            "get_finnhub_company_insider_transactions",
            "get_simfin_balance_sheet",
            "get_simfin_cashflow",
            "get_simfin_income_stmt",
            "get_macro_analysis",
            "get_economic_indicators",
            "get_yield_curve_analysis",
            "get_macro_news_openai",
            "get_sellthenews_macro_news",
        ):
            setattr(self, name, Tool(name))

    def has_alpaca_credentials(self):
        return self._alpaca

    def has_openai_web_search(self):
        return self._openai

    def has_finnhub(self):
        return self._finnhub

    def has_alpha_vantage(self):
        return (
            bool(self.config.get("online_tools", True))
            and bool(self.config.get("alpha_vantage_mcp_enabled", True))
            and bool(self.config.get("alpha_vantage_fundamentals_enabled", True))
            and self._alpha_vantage
        )

    def has_coindesk(self):
        return self._coindesk

    def has_simfin_data(self):
        return self._simfin

    def has_fred(self):
        return self._fred

    def has_sellthenews(self, feature_key=None):
        return (
            bool(self.config.get("online_tools", True))
            and bool(self.config.get("sellthenews_enabled", True))
            and bool(self.config.get(feature_key, True) if feature_key else True)
        )


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


def test_market_analyst_binds_options_tool_when_enabled_for_stock():
    llm = CapturingLLM()
    node = create_market_analyst(
        llm,
        FakeToolkit(config={"sellthenews_options_enabled": True}),
    )

    node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert "get_sellthenews_options_data" in llm.bound_tool_names[-1]


def test_market_analyst_does_not_bind_options_tool_for_crypto():
    llm = CapturingLLM()
    node = create_market_analyst(
        llm,
        FakeToolkit(config={"sellthenews_options_enabled": True}),
    )

    node({"trade_date": "2026-01-02", "company_of_interest": "BTC/USD", "messages": []})

    assert "get_sellthenews_options_data" not in llm.bound_tool_names[-1]


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


def test_market_analyst_preserves_deepseek_reasoning_content_between_tool_rounds():
    llm = ToolRoundTripLLM()
    node = create_market_analyst(llm, FakeToolkit(config={"max_tool_iterations_per_agent": 1}))

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in result["market_report"]
    second_round_messages = llm.calls[1].to_messages()
    assistant_tool_message = next(
        message
        for message in second_round_messages
        if isinstance(message, AIMessage) and message.additional_kwargs.get("tool_calls")
    )
    assert assistant_tool_message.additional_kwargs["reasoning_content"] == "reason before tool"


def test_news_analyst_routes_crypto_to_coindesk_and_stock_to_finnhub():
    stock_llm = CapturingLLM()
    crypto_llm = CapturingLLM()

    stock_node = create_news_analyst(stock_llm, FakeToolkit(config={"news_global_openai_enabled": False}))
    crypto_node = create_news_analyst(crypto_llm, FakeToolkit(config={"news_global_openai_enabled": False}))

    stock_node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})
    crypto_node({"trade_date": "2026-01-02", "company_of_interest": "BTC/USD", "messages": []})

    assert stock_llm.bound_tool_names[-1][0] == "get_sellthenews_stock_news"
    assert crypto_llm.bound_tool_names[-1][0] == "get_sellthenews_stock_news"
    assert "get_finnhub_news_recent" in stock_llm.bound_tool_names[-1]
    assert "get_coindesk_news" not in stock_llm.bound_tool_names[-1]
    assert "get_coindesk_news" in crypto_llm.bound_tool_names[-1]
    assert "get_finnhub_news_recent" not in crypto_llm.bound_tool_names[-1]


def test_social_media_analyst_writes_sentiment_report_and_appends_final_proposal():
    llm = CapturingLLM(["Social analysis body.", "FINAL TRANSACTION PROPOSAL: **BUY**"])
    node = create_social_media_analyst(
        llm,
        FakeToolkit(config={"grounded_social_evidence_enabled": False}),
    )

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert "Social analysis body." in result["sentiment_report"]
    assert "FINAL TRANSACTION PROPOSAL: **BUY**" in result["sentiment_report"]
    assert llm.bound_tool_names[-1][0] == "get_sellthenews_social_sentiment"
    assert "get_reddit_stock_info" in llm.bound_tool_names[-1]
    assert llm.bound_tool_names[-1][-1] == "get_stock_news_openai"


def test_social_media_analyst_can_disable_openai_stock_news_explicitly():
    llm = CapturingLLM(["Social analysis body.", "FINAL TRANSACTION PROPOSAL: **BUY**"])
    node = create_social_media_analyst(
        llm,
        FakeToolkit(
            config={
                "grounded_social_evidence_enabled": False,
                "social_openai_stock_news_enabled": False,
            }
        ),
    )

    node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert llm.bound_tool_names[-1][0] == "get_sellthenews_social_sentiment"
    assert "get_stock_news_openai" not in llm.bound_tool_names[-1]
    assert "get_reddit_stock_info" in llm.bound_tool_names[-1]


def test_social_media_analyst_injects_grounded_evidence_without_losing_horizon(monkeypatch):
    captured = []
    llm = CapturingLLM(["Grounded social analysis.\nFINAL TRANSACTION PROPOSAL: **HOLD**"])
    toolkit = FakeToolkit(config={"trading_horizon": "position"})
    node = create_social_media_analyst(llm, toolkit)
    monkeypatch.setattr(
        "tradingagents.agents.analysts.social_media_analyst.build_grounded_social_evidence",
        lambda *_args, **_kwargs: (
            "Grounded social/news evidence block:\n"
            "- Source: StockTwits public symbol stream\n"
            "- Sample count: 1\n"
            "- Source: Reddit public JSON search\n"
            "- Sample count: 2"
        ),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.social_media_analyst.capture_agent_prompt",
        lambda report_type, prompt_content, symbol=None: captured.append(
            (report_type, prompt_content, symbol)
        ),
    )

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    prompt_text = captured[-1][1]
    assert captured[-1][0] == "sentiment_report"
    assert captured[-1][2] == "AAPL"
    assert "Grounded social/news evidence block" in prompt_text
    assert "StockTwits public symbol stream" in prompt_text
    assert "Reddit public JSON search" in prompt_text
    assert "Selected horizon: Position" in prompt_text
    assert "SWING TRADING" not in prompt_text
    assert "Source conflict:" in prompt_text
    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in result["sentiment_report"]


def test_fundamentals_analyst_writes_report_and_routes_crypto_to_defillama():
    llm = CapturingLLM(["Fundamentals analysis body.", "FINAL TRANSACTION PROPOSAL: **HOLD**"])
    node = create_fundamentals_analyst(llm, FakeToolkit())

    result = node({"trade_date": "2026-01-02", "company_of_interest": "BTC/USD", "messages": []})

    assert "Fundamentals analysis body." in result["fundamentals_report"]
    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in result["fundamentals_report"]
    assert "get_defillama_fundamentals" in llm.bound_tool_names[-1]


def test_fundamentals_analyst_includes_finnhub_company_fundamentals_for_stocks():
    llm = CapturingLLM()
    node = create_fundamentals_analyst(
        llm,
        FakeToolkit(alpha_vantage=False, openai=False, simfin=False, finnhub=True),
    )

    node({"trade_date": "2026-01-02", "company_of_interest": "LI", "messages": []})

    assert llm.bound_tool_names[-1] == [
        "get_finnhub_company_fundamentals",
        "get_finnhub_company_insider_sentiment",
        "get_finnhub_company_insider_transactions",
    ]


def test_fundamentals_analyst_prefers_alpha_vantage_for_stocks():
    llm = CapturingLLM(["Fundamentals analysis body.", "FINAL TRANSACTION PROPOSAL: **HOLD**"])
    node = create_fundamentals_analyst(llm, FakeToolkit())

    node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert llm.bound_tool_names[-1][0] == "get_alpha_vantage_fundamentals"
    assert "get_fundamentals_openai" in llm.bound_tool_names[-1]
    assert "get_finnhub_company_insider_transactions" in llm.bound_tool_names[-1]


def test_macro_analyst_writes_report_and_appends_final_proposal():
    llm = CapturingLLM(["Macro analysis body.", "FINAL TRANSACTION PROPOSAL: **SELL**"])
    node = create_macro_analyst(llm, FakeToolkit())

    result = node({"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []})

    assert "Macro analysis body." in result["macro_report"]
    assert "FINAL TRANSACTION PROPOSAL: **SELL**" in result["macro_report"]
    assert llm.bound_tool_names[-1] == [
        "get_sellthenews_macro_news",
        "get_macro_analysis",
        "get_economic_indicators",
        "get_yield_curve_analysis",
        "get_macro_news_openai",
    ]


def test_sellthenews_tools_are_disabled_when_offline():
    news_llm = CapturingLLM()
    social_llm = CapturingLLM()
    macro_llm = CapturingLLM()
    toolkit = FakeToolkit(config={"online_tools": False})

    create_news_analyst(news_llm, toolkit)(
        {"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []}
    )
    create_social_media_analyst(social_llm, toolkit)(
        {"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []}
    )
    create_macro_analyst(macro_llm, toolkit)(
        {"trade_date": "2026-01-02", "company_of_interest": "AAPL", "messages": []}
    )

    assert "get_sellthenews_stock_news" not in news_llm.bound_tool_names[-1]
    assert "get_sellthenews_social_sentiment" not in social_llm.bound_tool_names[-1]
    assert "get_sellthenews_macro_news" not in macro_llm.bound_tool_names[-1]

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.social_media_analyst import create_social_media_analyst
from tradingagents.agents.utils.agent_utils import (
    _score_output_quality,
    _should_retry_tool_output,
)
from tradingagents.default_config import DEFAULT_CONFIG


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeToolkit:
    def __init__(self, config):
        self.config = config
        self.get_google_news = FakeTool("get_google_news")
        self.get_global_news_openai = FakeTool("get_global_news_openai")
        self.get_finnhub_news_recent = FakeTool("get_finnhub_news_recent")
        self.get_coindesk_news = FakeTool("get_coindesk_news")
        self.get_sellthenews_stock_news = FakeTool("get_sellthenews_stock_news")
        self.get_sellthenews_social_sentiment = FakeTool("get_sellthenews_social_sentiment")
        self.get_stock_news_openai = FakeTool("get_stock_news_openai")
        self.get_reddit_stock_info = FakeTool("get_reddit_stock_info")
        self.get_reddit_news = FakeTool("get_reddit_news")

    def has_openai_web_search(self):
        return True

    def has_finnhub(self):
        return True

    def has_coindesk(self):
        return True

    def has_sellthenews(self, feature_key=None):
        return (
            bool(self.config.get("online_tools", True))
            and bool(self.config.get("sellthenews_enabled", True))
            and bool(self.config.get(feature_key, True) if feature_key else True)
        )


class CapturingLLM:
    def __init__(self):
        self.bound_tool_names = []

    def bind_tools(self, tools):
        self.bound_tool_names.append([tool.name for tool in tools])
        return RunnableLambda(
            lambda _messages: AIMessage(
                content="FINAL TRANSACTION PROPOSAL: **HOLD**\nNews analysis."
            )
        )


class NewsLatencyControlTests(unittest.TestCase):
    def test_news_analyst_excludes_broad_global_openai_by_default(self):
        config = DEFAULT_CONFIG.copy()
        config.update({"online_tools": True, "news_global_openai_enabled": False})
        llm = CapturingLLM()
        node = create_news_analyst(llm, FakeToolkit(config))

        with patch("tradingagents.agents.analysts.news_analyst.capture_agent_prompt"):
            result = node(
                {
                    "trade_date": "2026-05-03",
                    "company_of_interest": "NVDA",
                    "messages": [],
                }
            )

        self.assertIn("FINAL TRANSACTION PROPOSAL: **HOLD**", result["news_report"])
        self.assertEqual(llm.bound_tool_names[-1][0], "get_sellthenews_stock_news")
        self.assertIn("get_google_news", llm.bound_tool_names[-1])
        self.assertIn("get_finnhub_news_recent", llm.bound_tool_names[-1])
        self.assertNotIn("get_global_news_openai", llm.bound_tool_names[-1])

    def test_news_analyst_can_enable_broad_global_openai_explicitly(self):
        config = DEFAULT_CONFIG.copy()
        config.update({"online_tools": True, "news_global_openai_enabled": True})
        llm = CapturingLLM()
        node = create_news_analyst(llm, FakeToolkit(config))

        with patch("tradingagents.agents.analysts.news_analyst.capture_agent_prompt"):
            node(
                {
                    "trade_date": "2026-05-03",
                    "company_of_interest": "NVDA",
                    "messages": [],
                }
            )

        self.assertEqual(llm.bound_tool_names[-1][0], "get_sellthenews_stock_news")
        self.assertIn("get_global_news_openai", llm.bound_tool_names[-1])

    def test_global_news_semantic_retry_is_disabled_by_default(self):
        quality = _score_output_quality("get_global_news_openai", "short")

        self.assertIn("undersized_output", quality["flags"])
        self.assertFalse(
            _should_retry_tool_output(
                "get_global_news_openai",
                uses_web_search=True,
                semantic_retry_enabled=True,
                retry_count=0,
                max_semantic_retries=1,
                quality=quality,
                config=DEFAULT_CONFIG,
            )
        )

    def test_stock_news_openai_can_still_retry_when_used(self):
        quality = _score_output_quality("get_stock_news_openai", "short")

        self.assertTrue(
            _should_retry_tool_output(
                "get_stock_news_openai",
                uses_web_search=True,
                semantic_retry_enabled=True,
                retry_count=0,
                max_semantic_retries=1,
                quality=quality,
                config=DEFAULT_CONFIG,
            )
        )

    def test_social_analyst_keeps_openai_stock_news_as_low_priority_backstop(self):
        config = DEFAULT_CONFIG.copy()
        config.update({"online_tools": True, "grounded_social_evidence_enabled": False})
        llm = CapturingLLM()
        node = create_social_media_analyst(llm, FakeToolkit(config))

        with patch("tradingagents.agents.analysts.social_media_analyst.capture_agent_prompt"):
            result = node(
                {
                    "trade_date": "2026-05-03",
                    "company_of_interest": "LI",
                    "messages": [],
                }
            )

        self.assertIn("FINAL TRANSACTION PROPOSAL: **HOLD**", result["sentiment_report"])
        self.assertEqual(llm.bound_tool_names[-1][0], "get_sellthenews_social_sentiment")
        self.assertIn("get_reddit_stock_info", llm.bound_tool_names[-1])
        self.assertEqual(llm.bound_tool_names[-1][-1], "get_stock_news_openai")

    def test_social_analyst_can_disable_openai_stock_news_explicitly(self):
        config = DEFAULT_CONFIG.copy()
        config.update(
            {
                "online_tools": True,
                "grounded_social_evidence_enabled": False,
                "social_openai_stock_news_enabled": False,
            }
        )
        llm = CapturingLLM()
        node = create_social_media_analyst(llm, FakeToolkit(config))

        with patch("tradingagents.agents.analysts.social_media_analyst.capture_agent_prompt"):
            node(
                {
                    "trade_date": "2026-05-03",
                    "company_of_interest": "LI",
                    "messages": [],
                }
            )

        self.assertEqual(llm.bound_tool_names[-1][0], "get_sellthenews_social_sentiment")
        self.assertNotIn("get_stock_news_openai", llm.bound_tool_names[-1])


if __name__ == "__main__":
    unittest.main()

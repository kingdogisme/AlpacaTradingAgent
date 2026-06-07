import unittest
import warnings
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

from tradingagents.agents.schemas import (
    AlpacaIntent,
    AdvisoryRating,
    ExecutableAction,
    ResearchPlan,
    RiskDecision,
    TraderProposal,
    render_research_plan,
    render_risk_decision,
    render_trader_proposal,
)
from tradingagents.agents.utils.gpt5_llm import GPT5ChatModel
from tradingagents.agents.utils.structured import bind_structured
from tradingagents.agents.utils.agent_trading_modes import extract_recommendation
from tradingagents.agents.utils.structured import invoke_structured_or_freetext
from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI


class Message:
    def __init__(self, content):
        self.content = content


class PlainLLM:
    def invoke(self, _prompt):
        return Message("plain fallback\nFINAL TRANSACTION PROPOSAL: **HOLD**")


class BrokenStructuredLLM:
    def invoke(self, _prompt):
        raise RuntimeError("structured unavailable")


class BrokenBindToolsLLM:
    def bind_tools(self, *_args, **_kwargs):
        raise RuntimeError("tool binding unavailable")

    def with_structured_output(self, _schema):
        raise NotImplementedError("structured unavailable")

    def invoke(self, _prompt):
        return Message("plain fallback\nFINAL TRANSACTION PROPOSAL: **HOLD**")


class FakeResponsesClient:
    def __init__(self, *, tool_name="ResearchPlan", arguments=None):
        self.calls = []
        self.responses = self
        self.tool_name = tool_name
        self.arguments = arguments or {
            "recommendation": "HOLD",
            "confidence": "medium",
            "rationale": "Evidence is mixed.",
            "strategic_actions": "Wait for confirmation.",
        }

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_1",
                    name=self.tool_name,
                    arguments=self.arguments,
                )
            ],
            output_text="",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2),
        )


class StructuredDecisionTests(unittest.TestCase):
    def test_renderers_preserve_exact_executable_action_line(self):
        research = render_research_plan(
            ResearchPlan(
                recommendation=ExecutableAction.BUY,
                confidence="medium",
                advisory_rating=AdvisoryRating.STRONG_BUY,
                rationale="Evidence supports upside.",
                strategic_actions="Enter on confirmation.",
            )
        )
        trader = render_trader_proposal(
            TraderProposal(
                action=ExecutableAction.LONG,
                confidence="high",
                reasoning="Trend and macro align.",
            )
        )
        risk = render_risk_decision(
            RiskDecision(
                action=ExecutableAction.SELL,
                human_action=ExecutableAction.SELL,
                alpaca_intent=AlpacaIntent.IMMEDIATE_ORDER,
                confidence="low",
                risk_rationale="Downside exceeds reward.",
                required_controls="Do not re-enter without reversal.",
                user_recommendation="Exit the current long and keep it off the buy list.",
                alpaca_action_plan="SELL: close the existing long position.",
                time_horizon="3-6 months",
                thesis="Quarterly trend is broken.",
                invalidation="Reclaim weekly trend support.",
                review_cadence="Quarterly",
                position_plan="Exit the trend position.",
                risk_budget="No new exposure until thesis repairs.",
            )
        )

        self.assertIn("**Advisory Rating**: STRONG BUY", research)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **BUY**", research)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **LONG**", trader)
        self.assertIn("**Human Investment Action**: SELL", risk)
        self.assertIn("**Alpaca Intent**: IMMEDIATE_ORDER", risk)
        self.assertIn("**User Recommendation**: Exit the current long and keep it off the buy list.", risk)
        self.assertIn("**Alpaca Execution Action**: SELL: close the existing long position.", risk)
        self.assertIn("**Invalidation**: Reclaim weekly trend support.", risk)
        self.assertIn("**Review Cadence**: Quarterly", risk)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **SELL**", risk)
        self.assertEqual(extract_recommendation(research, "investment"), "BUY")

    def test_renderers_use_chinese_labels_when_requested(self):
        research = render_research_plan(
            ResearchPlan(
                recommendation=ExecutableAction.HOLD,
                confidence="medium",
                advisory_rating=AdvisoryRating.HOLD,
                rationale="等待确认。",
                strategic_actions="暂不追价。",
                time_horizon="3-6个月",
            ),
            "zh-CN",
        )
        trader = render_trader_proposal(
            TraderProposal(
                action=ExecutableAction.HOLD,
                confidence="medium",
                reasoning="趋势未坏，但入场赔率不足。",
            ),
            "zh-CN",
        )
        risk = render_risk_decision(
            RiskDecision(
                action=ExecutableAction.HOLD,
                confidence="medium",
                risk_rationale="无现仓，等待确认更优。",
                required_controls="突破确认后再分批。",
                user_recommendation="观察名单，等待突破确认。",
                alpaca_action_plan="HOLD：当前不发送订单。",
            ),
            "zh-CN",
        )

        self.assertIn("**建议**: HOLD", research)
        self.assertIn("**顾问评级**: Hold", research)
        self.assertIn("**时间周期**: 3-6个月", research)
        self.assertIn("**操作**: HOLD", trader)
        self.assertIn("**判断依据**: 趋势未坏，但入场赔率不足。", trader)
        self.assertIn("**给用户的操作建议**: 观察名单，等待突破确认。", risk)
        self.assertIn("**人类投资动作**: HOLD", risk)
        self.assertIn("**Alpaca 意图**: NO_ORDER", risk)
        self.assertIn("**Alpaca 执行计划**: HOLD：当前不发送订单。", risk)
        self.assertIn("**风险理由**: 无现仓，等待确认更优。", risk)
        self.assertIn("**必要风控**: 突破确认后再分批。", risk)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **HOLD**", risk)

    def test_structured_advisory_strong_sell_remains_metadata_only(self):
        research = render_research_plan(
            ResearchPlan(
                recommendation=ExecutableAction.HOLD,
                confidence="low",
                advisory_rating=AdvisoryRating.STRONG_SELL,
                rationale="Downside risk is elevated, but shorts are disabled.",
                strategic_actions="Stay in cash unless the thesis repairs.",
            )
        )

        self.assertIn("**Advisory Rating**: STRONG SELL", research)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **HOLD**", research)
        self.assertEqual(extract_recommendation(research, "investment"), "HOLD")

    def test_structured_failure_falls_back_to_plain_text(self):
        content = invoke_structured_or_freetext(
            BrokenStructuredLLM(),
            PlainLLM(),
            "prompt",
            lambda value: value,
            "Unit Agent",
        )

        self.assertIn("FINAL TRANSACTION PROPOSAL: **HOLD**", content)

    def test_bind_structured_falls_back_when_tool_binding_is_unavailable(self):
        structured = bind_structured(BrokenBindToolsLLM(), ResearchPlan, "Research Manager")

        self.assertIsNone(structured)

    def test_gpt5_structured_output_binds_pydantic_schema_as_tool(self):
        llm = GPT5ChatModel(
            model="gpt-5.4",
            api_key="test-key",
            base_url="http://127.0.0.1:8317/v1",
        )
        structured = bind_structured(llm, ResearchPlan, "Research Manager")
        fake_client = FakeResponsesClient()
        structured_llm = structured.steps[0]
        structured_llm.__pydantic_private__["_client"] = fake_client

        parsed = structured.invoke("Return a research plan.")

        self.assertEqual(parsed.recommendation, ExecutableAction.HOLD)
        payload = fake_client.calls[0]
        self.assertEqual(payload["tool_choice"], "required")
        self.assertEqual(payload["tools"][0]["name"], "ResearchPlan")
        self.assertIn("recommendation", payload["tools"][0]["parameters"]["properties"])

    def test_gpt5_tool_only_response_is_not_logged_as_warning(self):
        llm = GPT5ChatModel(
            model="gpt-5.4",
            api_key="test-key",
            base_url="http://127.0.0.1:8317/v1",
        )
        structured = bind_structured(llm, ResearchPlan, "Research Manager")
        structured.steps[0].__pydantic_private__["_client"] = FakeResponsesClient()

        stdout = StringIO()
        with redirect_stdout(stdout):
            parsed = structured.invoke("Return a research plan.")

        self.assertEqual(parsed.recommendation, ExecutableAction.HOLD)
        output = stdout.getvalue()
        self.assertIn("No text content; response contains tool calls only.", output)
        self.assertNotIn("WARNING: No content extracted from response!", output)

    def test_gpt5_decision_schemas_do_not_emit_parsed_serializer_warning(self):
        llm = GPT5ChatModel(
            model="gpt-5.4",
            api_key="test-key",
            base_url="http://127.0.0.1:8317/v1",
        )
        cases = [
            (
                ResearchPlan,
                "Research Manager",
                FakeResponsesClient(),
                "recommendation",
            ),
            (
                TraderProposal,
                "Trader",
                FakeResponsesClient(
                    tool_name="TraderProposal",
                    arguments={
                        "action": "HOLD",
                        "confidence": "medium",
                        "reasoning": "Evidence is mixed.",
                    },
                ),
                "action",
            ),
            (
                RiskDecision,
                "Risk Manager",
                FakeResponsesClient(
                    tool_name="RiskDecision",
                    arguments={
                        "action": "HOLD",
                        "confidence": "medium",
                        "risk_rationale": "Risk and reward are balanced.",
                        "required_controls": "Wait for confirmation.",
                    },
                ),
                "action",
            ),
        ]

        for schema, agent_name, fake_client, action_field in cases:
            structured = bind_structured(llm, schema, agent_name)
            structured.steps[0].__pydantic_private__["_client"] = fake_client

            with self.subTest(schema=schema.__name__):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    parsed = structured.invoke(f"Return a {schema.__name__}.")

                self.assertEqual(getattr(parsed, action_field), ExecutableAction.HOLD)
                warning_text = "\n".join(str(warning.message) for warning in caught)
                self.assertNotIn("Pydantic serializer warnings", warning_text)
                self.assertNotIn("field_name='parsed'", warning_text)

    def test_gpt5_structured_output_include_raw_uses_plain_result_shape(self):
        llm = GPT5ChatModel(
            model="gpt-5.4",
            api_key="test-key",
            base_url="http://127.0.0.1:8317/v1",
        )
        structured = llm.with_structured_output(ResearchPlan, include_raw=True)
        structured.steps[0].__pydantic_private__["_client"] = FakeResponsesClient()

        result = structured.invoke("Return a research plan.")

        self.assertEqual(result["parsed"].recommendation, ExecutableAction.HOLD)
        self.assertIsNone(result["parsing_error"])
        self.assertTrue(hasattr(result["raw"], "tool_calls"))

    def test_chat_openai_structured_binding_uses_local_tool_adapter(self):
        llm = NormalizedChatOpenAI(
            model="gpt-5.5",
            api_key="test-key",
            base_url="http://127.0.0.1:8317/v1",
        )

        structured = bind_structured(llm, ResearchPlan, "Research Manager")

        self.assertEqual(len(structured.steps), 1)
        self.assertNotIn("PydanticToolsParser", repr(structured))
        self.assertIn("tools", structured.steps[0].kwargs)
        self.assertEqual(
            structured.steps[0].kwargs["tools"][0]["function"]["name"],
            "ResearchPlan",
        )
        self.assertEqual(structured.steps[0].kwargs["tool_choice"], "required")


if __name__ == "__main__":
    unittest.main()

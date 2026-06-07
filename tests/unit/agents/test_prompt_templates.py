import os
import string
import tempfile
import unittest
from pathlib import Path

from tradingagents.prompts import (
    PromptTemplateError,
    list_prompt_templates,
    load_prompt,
    render_prompt,
)
from tradingagents.agents.utils.language import language_instruction, output_language


class DefaultPromptValues(dict):
    def __missing__(self, key):
        value = f"<{key}>"
        self[key] = value
        return value


class PromptTemplateTests(unittest.TestCase):
    expected_groups = {
        "analysts",
        "graph",
        "horizons",
        "managers",
        "researchers",
        "risk",
        "shared",
        "trader",
        "trading_modes",
    }

    def test_core_prompt_templates_are_available(self):
        templates = set(list_prompt_templates())
        expected = {
            "shared/analyst_tool_system.md",
            "analysts/market_system.md",
            "managers/research_manager.md",
            "trader/trader_system.md",
            "managers/risk_manager.md",
            "graph/signal_extraction_system.md",
            "graph/reflection_system.md",
        }
        self.assertTrue(expected.issubset(templates))

    def test_templates_are_grouped_for_searchability(self):
        templates = list_prompt_templates()
        root_files = {template for template in templates if "/" not in template}
        grouped = {template.split("/", 1)[0] for template in templates if "/" in template}

        self.assertEqual(root_files, {"README.md"})
        self.assertEqual(grouped, self.expected_groups)

    def test_every_model_template_loads_and_renders_with_sample_values(self):
        values = DefaultPromptValues(
            {
                "actions": "BUY, HOLD, or SELL",
                "agent_context": "Agent context.",
                "analysis_content": "Analysis content.",
                "analysis_context": "Analysis packet.",
                "asset_context": "The company we want to look at is NVDA",
                "base_context": "Base trading context.",
                "current_date": "2026-05-03",
                "current_position": "NEUTRAL",
                "decision_format": "BUY/HOLD/SELL",
                "final_decision": "FINAL TRANSACTION PROPOSAL: **HOLD**",
                "final_format": "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**",
                "active_plan_review_context": "No active conditional trade plan.",
                "mode_name": "SWING TRADING INVESTMENT MODE",
                "raw_return": "+1.0%",
                "ticker": "NVDA",
                "tool_names": "tool_a, tool_b",
            }
        )

        for template_name in list_prompt_templates():
            if template_name == "README.md":
                continue
            with self.subTest(template=template_name):
                template = load_prompt(template_name)
                rendered = template.format_map(values)
                self.assertIsInstance(rendered, str)
                self.assertGreater(len(rendered.strip()), 20)

    def test_default_output_language_is_chinese(self):
        self.assertEqual(output_language({}), "zh-CN")
        self.assertIn("zh-CN", language_instruction({}))

    def test_options_positioning_guidance_is_present(self):
        market_prompt = load_prompt("analysts/market_system")
        trader_prompt = load_prompt("trader/trader_context")
        conservative_prompt = load_prompt("risk/conservative_context")
        aggressive_prompt = load_prompt("risk/aggressive_context")
        neutral_prompt = load_prompt("risk/neutral_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")

        self.assertIn("gamma flip", market_prompt)
        self.assertIn("GEX", market_prompt)
        self.assertIn("evidence_completeness.status", market_prompt)
        self.assertIn("Gamma Flip, Call Wall, Put Wall, and Max Pain", market_prompt)
        self.assertIn("OPTIONS POSITIONING", trader_prompt)
        self.assertIn("gamma flip", trader_prompt)
        self.assertIn("negative gamma", conservative_prompt)
        self.assertIn("technical breakout", aggressive_prompt)
        self.assertIn("high-GEX strikes", neutral_prompt)
        self.assertIn("gamma flip", risk_manager_prompt)
        self.assertIn("Do not recommend option contracts", risk_manager_prompt)
        self.assertIn("Optimize risk-adjusted return", risk_manager_prompt)
        self.assertIn("excessive conservatism", risk_manager_prompt)
        self.assertIn("Lifecycle continuity comes first", risk_manager_prompt)
        self.assertIn("Do not silently move an already-satisfied BUY trigger", risk_manager_prompt)
        self.assertIn("Treat soft risks as sizing/confidence modifiers", risk_manager_prompt)

    def test_investment_mode_prompts_match_long_only_no_trade_semantics(self):
        investment_prompt = load_prompt("trading_modes/investment")
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")

        self.assertIn("BUY/HOLD/SELL in the final transaction proposal is the human investment action", investment_prompt)
        self.assertIn("Alpaca execution is controlled separately by Alpaca Intent", investment_prompt)
        self.assertIn("do not use SELL to express bearishness when there is no position", investment_prompt)
        self.assertIn("Treat no open position as the normal paper-trading starting point", investment_prompt)
        self.assertIn('use HOLD for "do not enter / wait / no trade"', investment_prompt)
        self.assertIn("reserve SELL for reducing or exiting an existing long position", investment_prompt)
        self.assertIn('SELL means exit/reduce', trader_prompt)
        self.assertIn("use HOLD for no-trade/watchlist only when new long risk is not justified", trader_prompt)
        self.assertIn("do not default to HOLD solely because the account is flat", risk_manager_prompt)

    def test_core_decision_prompts_optimize_risk_adjusted_return(self):
        research_manager_prompt = load_prompt("managers/research_manager")
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")

        self.assertIn("Optimize for risk-adjusted return", research_manager_prompt)
        self.assertIn("high-quality confirmed opportunity", research_manager_prompt)
        self.assertIn("Opportunity Cost", trader_prompt)
        self.assertIn("excessive conservatism", trader_prompt)
        self.assertIn("optimizes risk-adjusted return", risk_manager_prompt)

    def test_decision_prompts_require_current_actionability_before_buy(self):
        investment_prompt = load_prompt("trading_modes/investment")
        research_manager_prompt = load_prompt("managers/research_manager")
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")
        position_prompt = load_prompt("horizons/position")
        trend_prompt = load_prompt("horizons/trend")
        trader_horizon_prompt = load_prompt("horizons/agent_context_trader")
        risk_horizon_prompt = load_prompt("horizons/agent_context_risk_mgmt")

        self.assertIn("BUY actionability gate", investment_prompt)
        self.assertIn("Strong thesis but poor immediate entry quality can be human BUY", investment_prompt)
        self.assertIn("Separate thesis quality from current actionability", research_manager_prompt)
        self.assertIn("Actionability Gate", trader_prompt)
        self.assertIn("Now-vs-Trigger Discipline", trader_prompt)
        self.assertIn("Do not output BUY merely because the multi-month thesis is intact", risk_manager_prompt)
        self.assertIn("pre-order condition that is not currently satisfied", risk_manager_prompt)
        self.assertIn('do not treat "daily/weekly trend is not broken" as enough for BUY', position_prompt)
        self.assertIn('do not treat "quarterly thesis is intact" as enough for BUY', trend_prompt)
        self.assertIn("Do not call a future conditional entry a current BUY", trader_horizon_prompt)
        self.assertIn("conditional/no-order", risk_horizon_prompt)

    def test_advisory_rating_prompt_contract_is_metadata_only(self):
        research_manager_prompt = load_prompt("managers/research_manager")
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")
        signal_prompt = load_prompt("graph/signal_extraction_system")

        for prompt in (research_manager_prompt, trader_prompt, risk_manager_prompt):
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("STRONG BUY, BUY, HOLD, SELL, or STRONG SELL", prompt)
                self.assertIn("advisory metadata only", prompt)

        self.assertIn("Ignore Advisory Rating metadata", signal_prompt)

    def test_position_trend_prompts_support_paper_trade_entry(self):
        position_prompt = load_prompt("horizons/position")
        trend_prompt = load_prompt("horizons/trend")
        trader_horizon_prompt = load_prompt("horizons/agent_context_trader")
        risk_horizon_prompt = load_prompt("horizons/agent_context_risk_mgmt")
        research_manager_prompt = load_prompt("managers/research_manager")
        risk_manager_prompt = load_prompt("managers/risk_manager")

        self.assertIn("paper-trading/no-position evaluation", position_prompt)
        self.assertIn("HOLD should mean the setup is not yet worth new risk", position_prompt)
        self.assertIn("BUY can mean staged participation", trend_prompt)
        self.assertIn("Do not use HOLD solely because there is no existing position", trader_horizon_prompt)
        self.assertIn("Do not downgrade to HOLD solely because the account is flat", risk_horizon_prompt)
        self.assertIn("Do not choose HOLD solely because there is no current position", research_manager_prompt)
        self.assertIn("Use BUY when a new starter long is justified now", risk_manager_prompt)

    def test_final_report_separates_user_guidance_from_alpaca_action(self):
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")

        self.assertIn("User Recommendation", trader_prompt)
        self.assertIn("Alpaca Intent / Action Plan", trader_prompt)
        self.assertIn("Keep the user-facing recommendation separate", trader_prompt)
        self.assertIn("User Recommendation: actionable portfolio guidance", risk_manager_prompt)
        self.assertIn("Alpaca Intent: exactly one of NO_ORDER, CONDITIONAL_ORDER, or IMMEDIATE_ORDER", risk_manager_prompt)
        self.assertIn("SELL/STRONG SELL advisory views map to human HOLD", risk_manager_prompt)
        self.assertIn("research-only/no live order", trader_prompt)
        self.assertIn("do not imply a live Alpaca order will be placed", risk_manager_prompt)

    def test_position_sizing_policy_supports_trend_concentrated_portfolios(self):
        investment_prompt = load_prompt("trading_modes/investment")
        research_manager_prompt = load_prompt("managers/research_manager")
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")

        self.assertIn("trend-concentrated", investment_prompt)
        self.assertIn("deterministic sizing", investment_prompt.lower())
        self.assertIn("configured portfolio policy", research_manager_prompt)
        self.assertIn("{portfolio_policy_context}", research_manager_prompt)
        self.assertIn("{theme_basket_context}", trader_prompt)
        self.assertIn("{sizing_guidance_context}", risk_manager_prompt)
        for prompt in (
            investment_prompt,
            research_manager_prompt,
            trader_prompt,
            risk_manager_prompt,
        ):
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("risk-to-invalidation", prompt)
                self.assertIn("notional exposure", prompt)
                self.assertIn("theme", prompt.lower())

    def test_decision_policy_prompt_contract_is_present(self):
        trader_prompt = load_prompt("trader/trader_context")
        risk_manager_prompt = load_prompt("managers/risk_manager")
        research_manager_prompt = load_prompt("managers/research_manager")

        self.assertIn("{decision_policy_context}", trader_prompt)
        self.assertIn("{decision_policy_context}", risk_manager_prompt)
        self.assertIn("{decision_policy_context}", research_manager_prompt)
        for prompt in (trader_prompt, risk_manager_prompt):
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("Factor Weights", prompt)
                self.assertIn("Gate Checks", prompt)
                self.assertIn("Sizing Calculation", prompt)
                self.assertIn("Crowding Gate", prompt)
                self.assertIn("Momentum Crash Gate", prompt)
                self.assertIn("Academic Countercheck", prompt)

    def test_key_agent_templates_accept_language_instruction(self):
        values = DefaultPromptValues(
            {
                "actions": "BUY, HOLD, or SELL",
                "agent_context": "Agent context.",
                "all_reports_text": "Reports.",
                "anchor_guidance": "Anchor guidance.",
                "claim_matrix": "Claim matrix.",
                "current_neutral_response": "",
                "current_response": "",
                "current_risky_response": "",
                "current_safe_response": "",
                "debate_digest": "Digest.",
                "decision_format": "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**",
                "global_news_guidance": "",
                "history": "",
                "holding_period": "2-10 trading days",
                "horizon_agent_context": "Horizon context.",
                "horizon_label": "Swing",
                "iteration_guidance": "Iterate.",
                "language_instruction": language_instruction({"output_language": "zh-CN"}),
                "past_memory_str": "",
                "primary_timeframes": "1h/4h/1d",
                "risk_specific_context": "Risk context.",
                "source_guidance": "Source guidance.",
                "system_intro": "Intro.",
                "ticker": "AAPL",
                "trader_decision": "Trader plan.",
                "workflow_intro": "Workflow.",
                "workflow_step_two": "Step two.",
            }
        )
        templates = [
            "analysts/market_system",
            "analysts/news_system",
            "analysts/fundamentals_system",
            "analysts/macro_system",
            "analysts/social_system",
            "researchers/bull_researcher",
            "researchers/bear_researcher",
            "risk/aggressive_debator",
            "risk/conservative_debator",
            "risk/neutral_debator",
        ]

        for template_name in templates:
            with self.subTest(template=template_name):
                rendered = load_prompt(template_name).format_map(values)
                self.assertIn("Write the analysis in zh-CN", rendered)

    def test_template_placeholders_are_parseable(self):
        formatter = string.Formatter()
        for template_name in list_prompt_templates():
            with self.subTest(template=template_name):
                fields = [
                    field_name
                    for _, field_name, _, _ in formatter.parse(load_prompt(template_name))
                    if field_name
                ]
                self.assertTrue(all(" " not in field for field in fields))

    def test_render_prompt_substitutes_values(self):
        rendered = render_prompt(
            "shared/analyst_final_recommendation",
            analysis_label="market analysis",
            subject="NVDA",
            request="provide a final recommendation.",
            analysis_content="Technical evidence here.",
            closing_instruction="Conclude with the required final line.",
        )
        self.assertIn("NVDA", rendered)
        self.assertIn("Technical evidence here.", rendered)
        self.assertNotIn("{subject}", rendered)

    def test_missing_render_value_raises_clear_error(self):
        with self.assertRaisesRegex(PromptTemplateError, "Missing prompt value"):
            render_prompt("shared/analyst_final_recommendation", subject="NVDA")

    def test_rejects_path_traversal(self):
        with self.assertRaises(PromptTemplateError):
            load_prompt("../secrets")

    def test_prompt_dir_override(self):
        original = os.environ.get("TRADINGAGENTS_PROMPT_DIR")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                Path(temp_dir, "custom.md").write_text("Ticker: {ticker}", encoding="utf-8")
                Path(temp_dir, "analysts").mkdir()
                Path(temp_dir, "analysts", "market_system.md").write_text(
                    "Custom analyst prompt for {ticker}",
                    encoding="utf-8",
                )
                os.environ["TRADINGAGENTS_PROMPT_DIR"] = temp_dir
                self.assertEqual(render_prompt("custom", ticker="BTC/USD"), "Ticker: BTC/USD")
                self.assertEqual(
                    render_prompt("analysts/market_system", ticker="NVDA"),
                    "Custom analyst prompt for NVDA",
                )
                self.assertIn("investment decision", load_prompt("graph/signal_extraction_system"))
        finally:
            if original is None:
                os.environ.pop("TRADINGAGENTS_PROMPT_DIR", None)
            else:
                os.environ["TRADINGAGENTS_PROMPT_DIR"] = original


if __name__ == "__main__":
    unittest.main()

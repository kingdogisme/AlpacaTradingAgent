import unittest
from unittest.mock import patch

from cli import utils as cli_utils
from cli import main as cli_main


class CLIModelDiscoveryTests(unittest.TestCase):
    @patch("cli.utils.console.print")
    @patch("cli.utils.get_model_options_with_status")
    def test_prints_dynamic_discovery_status(self, mock_status, mock_print):
        mock_status.return_value = {
            "options": [{"label": "Gemini 3.1 Pro", "value": "gemini-3.1-pro-preview"}],
            "source": "dynamic",
            "message": "Discovered live provider models.",
        }

        options = cli_utils._print_model_discovery_status("google", "deep")

        self.assertEqual(options[0]["value"], "gemini-3.1-pro-preview")
        mock_print.assert_called_once()
        printed = mock_print.call_args.args[0]
        self.assertIn("Model discovery", printed)
        self.assertIn("Discovered live provider models.", printed)

    @patch("cli.utils.console.print")
    @patch("cli.utils.get_model_options_with_status")
    def test_prints_fallback_status(self, mock_status, mock_print):
        mock_status.return_value = {
            "options": [{"label": "Gemini 2.5 Flash", "value": "gemini-2.5-flash"}],
            "source": "fallback",
            "message": "Dynamic discovery unavailable: network down. Fell back to built-in model catalog.",
        }

        options = cli_utils._print_model_discovery_status("google", "quick")

        self.assertEqual(options[0]["value"], "gemini-2.5-flash")
        printed = mock_print.call_args.args[0]
        self.assertIn("Model discovery fallback", printed)
        self.assertIn("network down", printed)

    @patch("cli.utils.console.print")
    @patch("cli.utils.get_model_options_with_status")
    def test_prints_static_catalog_status(self, mock_status, mock_print):
        mock_status.return_value = {
            "options": [{"label": "GPT-5.4 Mini", "value": "gpt-5.4-mini"}],
            "source": "static",
            "message": "Using built-in OpenAI model catalog.",
        }

        options = cli_utils._print_model_discovery_status("openai", "quick")

        self.assertEqual(options[0]["value"], "gpt-5.4-mini")
        printed = mock_print.call_args.args[0]
        self.assertIn("Model catalog", printed)
        self.assertIn("built-in OpenAI model catalog", printed)

    @patch("cli.utils.questionary.select")
    @patch("cli.utils._print_model_discovery_status")
    def test_shallow_selector_uses_discovery_status_options(self, mock_status, mock_select):
        mock_status.return_value = [{"label": "Local A", "value": "local-a"}]
        mock_select.return_value.ask.return_value = "local-a"

        choice = cli_utils.select_shallow_thinking_agent("local_openai")

        self.assertEqual(choice, "local-a")
        mock_status.assert_called_once_with("local_openai", "quick")

    @patch("cli.utils.questionary.select")
    @patch("cli.utils._print_model_discovery_status")
    def test_deep_selector_uses_discovery_status_options(self, mock_status, mock_select):
        mock_status.return_value = [{"label": "Gemini 3.1 Pro", "value": "gemini-3.1-pro-preview"}]
        mock_select.return_value.ask.return_value = "gemini-3.1-pro-preview"

        choice = cli_utils.select_deep_thinking_agent("google")

        self.assertEqual(choice, "gemini-3.1-pro-preview")
        mock_status.assert_called_once_with("google", "deep")

    @patch("cli.utils.questionary.confirm")
    def test_trend_execution_selector_defaults_false(self, mock_confirm):
        mock_confirm.return_value.ask.return_value = False

        enabled = cli_utils.select_trend_execution_enabled()

        self.assertFalse(enabled)


class CLIHorizonSelectionTests(unittest.TestCase):
    @patch("cli.main.get_output_language", return_value="zh-CN")
    @patch("cli.main.select_checkpoint_enabled", return_value=False)
    @patch("cli.main.ask_anthropic_effort", return_value="")
    @patch("cli.main.ask_gemini_thinking_config", return_value="")
    @patch("cli.main.select_deep_thinking_agent", return_value="deep-model")
    @patch("cli.main.select_shallow_thinking_agent", return_value="quick-model")
    @patch("cli.main.get_backend_url", return_value="")
    @patch("cli.main.select_llm_provider", return_value="openai")
    @patch("cli.main.select_trend_execution_enabled", return_value=True)
    @patch("cli.main.select_trading_horizon", return_value="trend")
    @patch("cli.main.select_research_depth", return_value=3)
    @patch("cli.main.select_analysts", return_value=[])
    @patch("cli.main.get_ticker", return_value="AAPL")
    @patch("cli.main.console.print")
    def test_non_swing_horizon_captures_trend_execution_flag(
        self,
        _print,
        _ticker,
        _analysts,
        _depth,
        _horizon,
        mock_trend_exec,
        _provider,
        _backend,
        _quick,
        _deep,
        _gemini,
        _anthropic,
        _checkpoint,
        _language,
    ):
        selections = cli_main.get_user_selections()

        self.assertEqual(selections["trading_horizon"], "trend")
        self.assertEqual(selections["output_language"], "zh-CN")
        self.assertTrue(selections["trend_execution_enabled"])
        mock_trend_exec.assert_called_once()

    @patch("cli.main.get_output_language", return_value="zh-CN")
    @patch("cli.main.select_checkpoint_enabled", return_value=False)
    @patch("cli.main.ask_anthropic_effort", return_value="")
    @patch("cli.main.ask_gemini_thinking_config", return_value="")
    @patch("cli.main.select_deep_thinking_agent", return_value="deep-model")
    @patch("cli.main.select_shallow_thinking_agent", return_value="quick-model")
    @patch("cli.main.get_backend_url", return_value="")
    @patch("cli.main.select_llm_provider", return_value="openai")
    @patch("cli.main.select_trend_execution_enabled", return_value=True)
    @patch("cli.main.select_trading_horizon", return_value="swing")
    @patch("cli.main.select_research_depth", return_value=3)
    @patch("cli.main.select_analysts", return_value=[])
    @patch("cli.main.get_ticker", return_value="AAPL")
    @patch("cli.main.console.print")
    def test_swing_horizon_skips_trend_execution_prompt(
        self,
        _print,
        _ticker,
        _analysts,
        _depth,
        _horizon,
        mock_trend_exec,
        _provider,
        _backend,
        _quick,
        _deep,
        _gemini,
        _anthropic,
        _checkpoint,
        _language,
    ):
        selections = cli_main.get_user_selections()

        self.assertEqual(selections["trading_horizon"], "swing")
        self.assertFalse(selections["trend_execution_enabled"])
        mock_trend_exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import unittest
import warnings
from unittest.mock import patch

from tradingagents.openai_model_registry import (
    apply_responses_model_params,
    get_default_model_for_provider,
    get_model_options_for_provider,
    get_model_options_with_status,
    get_openai_model_options,
    get_provider_ui_metadata,
    normalize_model_params,
    resolve_model_choice,
)


class OpenAIModelRegistryTests(unittest.TestCase):
    def tearDown(self):
        from tradingagents.openai_model_registry import _get_dynamic_model_options

        _get_dynamic_model_options.cache_clear()

    def test_model_options_remove_deprecated_choices_and_keep_low_cost_model(self):
        quick_values = {option["value"] for option in get_openai_model_options("quick")}
        deep_values = {option["value"] for option in get_openai_model_options("deep")}

        self.assertIn("gpt-5.4-nano", quick_values)
        self.assertIn("gpt-5-nano", quick_values)
        self.assertIn("gpt-5.4-mini", deep_values)
        self.assertIn("gpt-5.4-pro", deep_values)

        removed_models = {"gpt-4o", "gpt-4o-mini", "o1", "o3", "o3-mini", "o4-mini"}
        self.assertFalse(removed_models & quick_values)
        self.assertFalse(removed_models & deep_values)

    def test_reasoning_model_params_are_limited_to_supported_options(self):
        params = normalize_model_params(
            "gpt-5-nano",
            {
                "reasoning_effort": "xhigh",
                "text_verbosity": "high",
                "temperature": 0.9,
            },
            role="quick",
        )

        self.assertEqual(params["reasoning_effort"], "minimal")
        self.assertEqual(params["text_verbosity"], "high")
        self.assertNotIn("temperature", params)

    def test_non_reasoning_model_exposes_sampling_params(self):
        params = normalize_model_params(
            "gpt-4.1",
            {"temperature": 2.5, "top_p": -1, "reasoning_effort": "high"},
            role="deep",
        )

        self.assertEqual(params["temperature"], 2.0)
        self.assertEqual(params["top_p"], 0.0)
        self.assertNotIn("reasoning_effort", params)

    def test_responses_payload_nests_reasoning_and_text_controls(self):
        payload = {
            "model": "gpt-5.4",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
            "text": {"format": {"type": "text"}},
        }

        apply_responses_model_params(
            payload,
            "gpt-5.4",
            {
                "reasoning_effort": "xhigh",
                "text_verbosity": "low",
                "reasoning_summary": "concise",
                "max_output_tokens": 128,
                "store": False,
            },
            role="deep",
        )

        self.assertEqual(payload["reasoning"], {"effort": "xhigh", "summary": "concise"})
        self.assertEqual(payload["text"]["verbosity"], "low")
        self.assertEqual(payload["max_output_tokens"], 128)
        self.assertFalse(payload["store"])

    @patch("tradingagents.openai_model_registry.discover_models")
    def test_provider_catalog_exposes_custom_model_paths_where_needed(self, mock_discover):
        def fake_discover(provider):
            if provider == "azure":
                raise RuntimeError("not supported")
            return [(f"{provider}-model", f"{provider}-model")]

        mock_discover.side_effect = fake_discover

        for provider in ("local_openai", "deepseek", "qwen", "glm", "openrouter", "ollama", "azure"):
            with self.subTest(provider=provider):
                values = {option["value"] for option in get_model_options_for_provider(provider, "quick")}
                self.assertIn("custom", values)

        self.assertFalse(get_provider_ui_metadata("openai")["backend_visible"])
        self.assertTrue(get_provider_ui_metadata("azure")["backend_visible"])

    @patch("tradingagents.openai_model_registry.discover_models")
    def test_openai_provider_defaults_use_available_local_models_after_switching(self, mock_discover):
        mock_discover.return_value = [("local-a", "local-a"), ("local-b", "local-b")]
        self.assertEqual(get_default_model_for_provider("openai", "quick"), "gpt-5.4-mini")
        self.assertEqual(get_default_model_for_provider("openai", "deep"), "gpt-5.4")
        self.assertEqual(get_default_model_for_provider("local_openai", "quick"), "local-a")

    @patch("tradingagents.openai_model_registry.discover_models")
    def test_deepseek_defaults_prefer_v4_flash_and_pro(self, mock_discover):
        mock_discover.return_value = [("DeepSeek V3.2", "deepseek-chat")]

        quick_result = get_model_options_with_status("deepseek", "quick")
        deep_result = get_model_options_with_status("deepseek", "deep")

        self.assertEqual(get_default_model_for_provider("deepseek", "quick"), "deepseek-v4-flash")
        self.assertEqual(get_default_model_for_provider("deepseek", "deep"), "deepseek-v4-pro")
        self.assertEqual(quick_result["options"][0]["value"], "deepseek-v4-flash")
        self.assertEqual(deep_result["options"][0]["value"], "deepseek-v4-pro")

    @patch("tradingagents.openai_model_registry.discover_models")
    def test_dynamic_discovery_preferred_for_supported_non_openai_providers(self, mock_discover):
        mock_discover.return_value = [("Gemini 3.1 Pro", "gemini-3.1-pro-preview")]
        result = get_model_options_with_status("google", "deep")
        values = result["options"]
        self.assertEqual(values[0]["value"], "gemini-3.1-pro-preview")
        self.assertEqual(result["source"], "dynamic")
        self.assertNotIn("custom", {option["value"] for option in values})

    @patch("tradingagents.openai_model_registry.discover_models")
    def test_falls_back_to_static_catalog_when_discovery_fails(self, mock_discover):
        mock_discover.side_effect = RuntimeError("network down")
        result = get_model_options_with_status("google", "quick")
        values = result["options"]
        self.assertEqual(result["source"], "fallback")
        self.assertIn("network down", result["message"])
        self.assertIn("gemini-2.5-flash", {option["value"] for option in values})

    @patch("tradingagents.openai_model_registry.discover_models")
    def test_local_openai_empty_discovery_falls_back_to_builtin_defaults(self, mock_discover):
        mock_discover.return_value = []

        result = get_model_options_with_status("local_openai", "quick")
        values = result["options"]

        self.assertEqual(result["source"], "fallback")
        self.assertIn("Dynamic discovery returned no models", result["message"])
        self.assertIn("gpt-5.4-mini", {option["value"] for option in values})
        self.assertIn("custom", {option["value"] for option in values})

    def test_custom_model_choice_resolves_to_runtime_model_id(self):
        self.assertEqual(resolve_model_choice("custom", " openai/gpt-5.4-mini "), "openai/gpt-5.4-mini")
        self.assertIsNone(resolve_model_choice("custom", " "))
        self.assertEqual(resolve_model_choice("gpt-5.4-mini", "ignored"), "gpt-5.4-mini")

    def test_unknown_openai_compatible_model_uses_custom_chat_controls(self):
        params = normalize_model_params(
            "qwen3:latest",
            {"temperature": 0.4, "top_p": 0.7, "reasoning_effort": "high"},
            role="quick",
        )

        self.assertEqual(params["temperature"], 0.4)
        self.assertEqual(params["top_p"], 0.7)
        self.assertNotIn("reasoning_effort", params)


class ValidatorsTests(unittest.TestCase):
    def test_validate_model_is_permissive_for_dynamic_runtime_models(self):
        from tradingagents.llm_clients.validators import validate_model

        self.assertTrue(validate_model("google", "gemini-future-9"))
        self.assertTrue(validate_model("openrouter", "openai/gpt-5.9-preview"))

    def test_permissive_validation_does_not_emit_unknown_model_warning(self):
        from tradingagents.llm_clients.google_client import GoogleClient

        with patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI"):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                GoogleClient("gemini-future-9", api_key="test-key").get_llm()

        runtime_warnings = [item for item in caught if issubclass(item.category, RuntimeWarning)]
        self.assertEqual(runtime_warnings, [])


if __name__ == "__main__":
    unittest.main()

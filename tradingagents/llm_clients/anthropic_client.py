import os
import time
from typing import Any

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient, UsageTrackingChatModel, normalize_content
from .validators import validate_model


class NormalizedChatAnthropic(UsageTrackingChatModel, ChatAnthropic):
    provider: str = "anthropic"
    model_role: str = "unknown"

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        call_started = time.time()
        result = super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )
        self._record_usage_result(
            messages=messages,
            result=result,
            latency_seconds=time.time() - call_started,
        )
        return result


class AnthropicClient(BaseLLMClient):
    def get_llm(self) -> Any:
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}
        if self.base_url:
            llm_kwargs["base_url"] = self.base_url
        api_key = self.kwargs.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Provider 'anthropic' requires ANTHROPIC_API_KEY.")
        llm_kwargs["api_key"] = api_key
        for key in ("timeout", "max_retries", "max_tokens", "callbacks", "http_client", "http_async_client", "effort"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]
        llm = NormalizedChatAnthropic(**llm_kwargs)
        llm.model_role = self.kwargs.get("model_role", "unknown")
        return llm

    def validate_model(self) -> bool:
        return validate_model("anthropic", self.model)

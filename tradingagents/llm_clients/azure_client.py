import os
import time
from typing import Any

from langchain_openai import AzureChatOpenAI

from .base_client import BaseLLMClient, UsageTrackingChatModel, normalize_content


class NormalizedAzureChatOpenAI(UsageTrackingChatModel, AzureChatOpenAI):
    provider: str = "azure"
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


class AzureOpenAIClient(BaseLLMClient):
    def get_llm(self) -> Any:
        api_key = self.kwargs.get("api_key") or os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = self.base_url or os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not api_key:
            raise ValueError("Provider 'azure' requires AZURE_OPENAI_API_KEY.")
        if not endpoint:
            raise ValueError("Provider 'azure' requires AZURE_OPENAI_ENDPOINT or backend_url.")

        llm_kwargs = {
            "model": self.model,
            "azure_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", self.model),
            "azure_endpoint": endpoint,
            "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            "api_key": api_key,
        }
        for key in ("timeout", "max_retries", "reasoning_effort", "callbacks", "http_client", "http_async_client"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]
        llm = NormalizedAzureChatOpenAI(**llm_kwargs)
        llm.model_role = self.kwargs.get("model_role", "unknown")
        return llm

    def validate_model(self) -> bool:
        return True

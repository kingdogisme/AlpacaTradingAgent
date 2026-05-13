from abc import ABC, abstractmethod
from typing import Any, Optional
import warnings

from langchain_core.messages import AIMessage
from langchain_core.messages.ai import add_usage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult


def normalize_content(response):
    """Normalize provider response content to a plain string."""
    content = getattr(response, "content", None)
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        response.content = "\n".join(t for t in texts if t)
    return response


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_usage_metadata(usage: Optional[dict]) -> dict[str, int]:
    """Flatten LangChain usage metadata into fields persisted in run logs."""
    usage = usage or {}
    input_details = (
        usage.get("input_token_details")
        or usage.get("input_tokens_details")
        or usage.get("prompt_tokens_details")
        or {}
    )
    output_details = (
        usage.get("output_token_details")
        or usage.get("output_tokens_details")
        or usage.get("completion_tokens_details")
        or {}
    )
    input_tokens = _as_int(usage.get("input_tokens", usage.get("prompt_tokens")))
    cache_hit_tokens = _as_int(
        usage.get(
            "prompt_cache_hit_tokens",
            usage.get("cache_hit_tokens", input_details.get("cache_read", input_details.get("cached_tokens"))),
        )
    )
    cache_creation_tokens = _as_int(
        usage.get("cache_creation_tokens", input_details.get("cache_creation"))
    )
    cache_miss_tokens = _as_int(usage.get("prompt_cache_miss_tokens", usage.get("cache_miss_tokens")))
    if cache_miss_tokens == 0:
        cache_miss_tokens = max(
            input_tokens - cache_hit_tokens - cache_creation_tokens,
            0,
        )

    return {
        "input_tokens": input_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "output_tokens": _as_int(usage.get("output_tokens", usage.get("completion_tokens"))),
        "reasoning_tokens": _as_int(output_details.get("reasoning", output_details.get("reasoning_tokens"))),
        "total_tokens": _as_int(usage.get("total_tokens")),
    }


def get_response_usage_metadata(response: LLMResult) -> Optional[dict]:
    """Aggregate AIMessage.usage_metadata from an LLMResult."""
    combined = None
    for generation_list in response.generations or []:
        for generation in generation_list or []:
            if not isinstance(generation, ChatGeneration):
                continue
            message = generation.message
            if isinstance(message, AIMessage) and message.usage_metadata:
                combined = add_usage(combined, message.usage_metadata)
    return combined


def get_message_usage_dict(message: Any) -> dict[str, int]:
    if isinstance(message, AIMessage) and message.usage_metadata:
        return normalize_usage_metadata(message.usage_metadata)
    return {}


class UsageTrackingChatModel:
    """Mixin that logs provider usage metadata for standard LangChain chat models."""

    def _provider_name_for_usage(self) -> str:
        return getattr(self, "provider", self.__class__.__name__.removeprefix("Normalized"))

    def _model_name_for_usage(self) -> str:
        return str(
            getattr(self, "model_name", None)
            or getattr(self, "model", None)
            or getattr(self, "deployment_name", None)
            or "unknown"
        )

    def _model_role_for_usage(self) -> str:
        return str(getattr(self, "model_role", None) or "unknown")

    def _extract_input_chars(self, messages: Any) -> int:
        return len(str(messages or ""))

    def _record_usage_result(
        self,
        *,
        messages: Any,
        result: ChatResult,
        latency_seconds: float,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        response = LLMResult(
            generations=[result.generations],
            llm_output=result.llm_output,
        )
        usage = normalize_usage_metadata(get_response_usage_metadata(response))
        raw_usage = normalize_usage_metadata((result.llm_output or {}).get("token_usage"))
        for key, value in raw_usage.items():
            if value or not usage.get(key):
                usage[key] = value
        if not any(usage.values()) and status == "success":
            return

        output_text = ""
        if result.generations:
            content = getattr(result.generations[0].message, "content", "")
            output_text = str(content or "")

        payload = {
            "model": self._model_name_for_usage(),
            "purpose": f"{self._provider_name_for_usage()}_chat",
            "model_role": self._model_role_for_usage(),
            "status": status,
            "latency_seconds": round(float(latency_seconds), 4),
            "input_chars": self._extract_input_chars(messages),
            "output_chars": len(output_text),
            "usage": usage,
            "error_message": error_message,
        }

        try:
            from webui.utils.state import app_state

            app_state.register_llm_call(
                model_name=payload["model"],
                purpose=payload["purpose"],
                latency_seconds=payload["latency_seconds"],
                input_chars=payload["input_chars"],
                output_chars=payload["output_chars"],
                usage=payload["usage"],
                status=status,
                error_message=error_message,
            )
        except Exception:
            try:
                from tradingagents.run_logger import get_run_audit_logger

                get_run_audit_logger().log_event(event_type="llm_call", payload=payload)
            except Exception:
                pass


class BaseLLMClient(ABC):
    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        provider = getattr(self, "provider", None)
        return str(provider) if provider else self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        if self.validate_model():
            return
        warnings.warn(
            (
                f"Model '{self.model}' is not in the known model list for "
                f"provider '{self.get_provider_name()}'. Continuing anyway."
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    @abstractmethod
    def get_llm(self) -> Any:
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        pass

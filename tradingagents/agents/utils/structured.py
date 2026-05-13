from __future__ import annotations

import logging
import json
from typing import Any, Callable, Optional, TypeVar

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ToolStructuredRunnable(Runnable):
    """Structured-output adapter that avoids LangChain's parsed-field wrapper."""

    def __init__(self, llm: Any, schema: type[BaseModel], *, include_raw: bool = False):
        self.schema = schema
        self.include_raw = include_raw
        self.steps = [llm.bind_tools([schema], tool_choice="any")]

    def invoke(self, input: Any, config: Optional[dict] = None, **kwargs: Any) -> Any:
        raw = self.steps[0].invoke(input, config=config, **kwargs)
        try:
            parsed = self._parse_tool_call(raw)
        except Exception as exc:
            if self.include_raw:
                return {"raw": raw, "parsed": None, "parsing_error": exc}
            raise

        if self.include_raw:
            return {"raw": raw, "parsed": parsed, "parsing_error": None}
        return parsed

    def _parse_tool_call(self, raw: AIMessage) -> BaseModel:
        tool_calls = list(getattr(raw, "tool_calls", None) or [])
        if not tool_calls:
            tool_calls = list(getattr(raw, "additional_kwargs", {}).get("tool_calls", []) or [])
        if not tool_calls:
            raise ValueError(f"{self.schema.__name__} structured output did not include a tool call")

        selected_call = self._select_tool_call(tool_calls)
        args = self._extract_tool_args(selected_call)
        if not isinstance(args, dict):
            raise ValueError(f"{self.schema.__name__} tool call arguments must be a JSON object")
        return self.schema(**args)

    def _select_tool_call(self, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
        for call in tool_calls:
            if self._tool_call_name(call) == self.schema.__name__:
                return call
        return tool_calls[0]

    @staticmethod
    def _tool_call_name(call: dict[str, Any]) -> Optional[str]:
        function_spec = call.get("function")
        if isinstance(function_spec, dict):
            return function_spec.get("name")
        return call.get("name")

    @staticmethod
    def _extract_tool_args(call: dict[str, Any]) -> Any:
        if "args" in call:
            return call["args"]

        function_spec = call.get("function")
        if isinstance(function_spec, dict):
            arguments = function_spec.get("arguments", {})
        else:
            arguments = call.get("arguments", {})

        if isinstance(arguments, str):
            return json.loads(arguments or "{}")
        return arguments or {}


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    if hasattr(llm, "bind_tools"):
        try:
            return ToolStructuredRunnable(llm, schema)
        except Exception as exc:
            logger.warning("%s tool-structured output unavailable; trying provider default (%s)", agent_name, exc)

    try:
        return llm.with_structured_output(schema)
    except (AttributeError, NotImplementedError) as exc:
        logger.warning("%s structured output unavailable; using free text (%s)", agent_name, exc)
        return None


def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    if structured_llm is not None:
        try:
            return render(structured_llm.invoke(prompt))
        except Exception as exc:
            logger.warning("%s structured output failed; retrying as free text (%s)", agent_name, exc)

    response = plain_llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)

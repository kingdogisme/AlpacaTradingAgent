"""Custom LangChain wrapper for OpenAI reasoning models using Responses API."""

from typing import Any, Dict, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import OpenAI
from pydantic import BaseModel, ConfigDict
import json
import time

from tradingagents.agents.utils.structured import ToolStructuredRunnable
from tradingagents.openai_model_registry import (
    apply_responses_model_params,
    describe_model_params as describe_registry_model_params,
    get_default_model_params,
    is_responses_model,
    normalize_model_params,
)


def get_model_params_for_depth(
    model_name: str,
    research_depth: str,
    model_role: str = "quick"
) -> Dict[str, Any]:
    """Backward-compatible shim.

    Research depth now controls debate rounds only. Model parameters come from
    per-model defaults or explicit UI overrides.
    """
    return get_default_model_params(model_name, model_role)


def describe_model_params(
    model_name: str,
    research_depth: str,
    model_role: str = "quick"
) -> str:
    """Backward-compatible description helper."""
    return describe_registry_model_params(model_name, None, model_role)


class GPT5ChatModel(BaseChatModel):
    """ChatModel wrapper for OpenAI reasoning models using responses.create()."""
    
    model: str = "gpt-5-mini"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    reasoning_effort: str = "medium"
    verbosity: str = "medium"  # low, medium, high
    summary: str = "auto"  # concise, detailed, auto, none
    max_output_tokens: Optional[int] = None
    store: bool = False
    parallel_tool_calls: bool = True
    model_role: str = "deep"
    
    # Internal client - not a pydantic field
    _client: Optional[OpenAI] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize the OpenAI client
        client_kwargs = {}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self._client = OpenAI(**client_kwargs) if client_kwargs else OpenAI()
    
    @property
    def _llm_type(self) -> str:
        return "openai-responses-chat"
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "verbosity": self.verbosity,
            "summary": self.summary,
            "max_output_tokens": self.max_output_tokens,
            "store": self.store,
            "parallel_tool_calls": self.parallel_tool_calls,
        }
    
    def _convert_messages_to_input(self, messages: List[BaseMessage]) -> List[Dict]:
        """Convert LangChain messages, dicts, or strings to GPT-5 input format."""
        input_messages = []
        
        for message in messages:
            # Support dict-style messages used in some agents
            if isinstance(message, dict):
                role = message.get("role", "user")
                content = message.get("content", "")
                # If content is already structured, pass through
                if isinstance(content, list):
                    input_messages.append({
                        "role": "developer" if role == "system" else role,
                        "content": content
                    })
                else:
                    content_type = "output_text" if role == "assistant" else "input_text"
                    input_messages.append({
                        "role": "developer" if role == "system" else role,
                        "content": [
                            {
                                "type": content_type,
                                "text": content
                            }
                        ]
                    })
                continue
            
            # Support raw string messages
            if isinstance(message, str):
                input_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": message
                        }
                    ]
                })
                continue

            # Support generic message objects with role/content attributes
            if hasattr(message, "role") and hasattr(message, "content"):
                role = getattr(message, "role") or "user"
                content = getattr(message, "content", "")
                content_type = "output_text" if role == "assistant" else "input_text"
                input_messages.append({
                    "role": "developer" if role == "system" else role,
                    "content": [
                        {
                            "type": content_type,
                            "text": content
                        }
                    ]
                })
                continue

            if isinstance(message, SystemMessage):
                # GPT-5 uses "developer" role instead of "system"
                input_messages.append({
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": message.content
                        }
                    ]
                })
            elif isinstance(message, HumanMessage):
                input_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": message.content
                        }
                    ]
                })
            elif isinstance(message, AIMessage):
                input_messages.append({
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": message.content
                        }
                    ]
                })
        
        return input_messages

    def _to_responses_function_tool(self, tool: Any) -> Optional[Dict[str, Any]]:
        """Convert LangChain/Pydantic/OpenAI tool specs to Responses function-tool shape."""
        try:
            converted = convert_to_openai_tool(tool)
        except Exception:
            converted = None

        if isinstance(converted, dict):
            normalized = self._normalize_openai_tool_dict(converted)
            if normalized:
                return normalized

        if isinstance(tool, dict):
            normalized = self._normalize_openai_tool_dict(tool)
            if normalized:
                return normalized

        tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        if not tool_name and hasattr(tool, "func"):
            tool_name = getattr(tool.func, "__name__", None)
        if not tool_name:
            return None

        tool_description = getattr(tool, "description", None)
        if not tool_description and getattr(tool, "__doc__", None):
            tool_description = tool.__doc__
        if not tool_description and hasattr(tool, "func"):
            tool_description = getattr(tool.func, "__doc__", None)

        tool_parameters = {"type": "object", "properties": {}}
        if hasattr(tool, "args_schema") and tool.args_schema:
            try:
                tool_parameters = tool.args_schema.schema()
            except Exception:
                pass
        elif hasattr(tool, "model_json_schema"):
            try:
                tool_parameters = tool.model_json_schema()
            except Exception:
                pass

        return {
            "type": "function",
            "name": str(tool_name),
            "description": tool_description or f"Tool: {tool_name}",
            "parameters": tool_parameters,
        }

    def _normalize_openai_tool_dict(self, tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if tool.get("type") != "function":
            return None

        function_spec = tool.get("function")
        if isinstance(function_spec, dict):
            name = function_spec.get("name")
            description = function_spec.get("description")
            parameters = function_spec.get("parameters")
            strict = function_spec.get("strict", tool.get("strict"))
        else:
            name = tool.get("name")
            description = tool.get("description")
            parameters = tool.get("parameters")
            strict = tool.get("strict")

        if not name:
            return None

        normalized = {
            "type": "function",
            "name": name,
            "description": description or f"Tool: {name}",
            "parameters": parameters or {"type": "object", "properties": {}},
        }
        if strict is not None:
            normalized["strict"] = strict
        return normalized

    def _normalize_tool_choice(self, tool_choice: Any) -> Any:
        if tool_choice in (None, False):
            return None
        if tool_choice == "any":
            return "required"
        if isinstance(tool_choice, str):
            return tool_choice
        if isinstance(tool_choice, dict):
            function_spec = tool_choice.get("function")
            if isinstance(function_spec, dict) and function_spec.get("name"):
                return {"type": "function", "name": function_spec["name"]}
            return tool_choice
        return None

    def with_structured_output(
        self,
        schema: Any,
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> ToolStructuredRunnable:
        """Bind a Pydantic schema without LangChain's parsed-field wrapper.

        LangChain's default structured-output adapter serializes an internal
        ``parsed`` field through Pydantic. For Pydantic schemas used by our
        decision agents that can emit serializer warnings even when parsing
        succeeds. This adapter keeps the same tool-calling contract while
        returning the parsed schema directly.
        """
        kwargs.pop("method", None)
        kwargs.pop("strict", None)
        if kwargs:
            raise ValueError(f"Received unsupported arguments {kwargs}")

        try:
            is_pydantic_schema = isinstance(schema, type) and issubclass(schema, BaseModel)
        except TypeError:
            is_pydantic_schema = False

        if is_pydantic_schema:
            return ToolStructuredRunnable(self, schema, include_raw=include_raw)

        return super().with_structured_output(schema, include_raw=include_raw)
    
    def _extract_content_from_response(self, response) -> tuple:
        """
        Extract text content and tool calls from GPT-5 response.
        Returns (content, tool_calls) tuple.
        
        Priority for content:
        1. response.output_text (convenience property with all text)
        2. Iterate through response.output items
        
        Tool calls are always extracted from response.output items.
        """
        tool_calls = []
        content_parts = []  # Use list to avoid duplication
        
        # Always iterate through output for tool calls
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                item_type = getattr(item, 'type', None)
                
                # Extract function calls
                if item_type == 'function_call':
                    call_id = getattr(item, 'call_id', None) or getattr(item, 'id', f'call_{len(tool_calls)+1}')
                    func_name = getattr(item, 'name', None)
                    func_args = getattr(item, 'arguments', {})
                    
                    if func_name:
                        tool_calls.append({
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": json.dumps(func_args) if isinstance(func_args, dict) else str(func_args)
                            }
                        })
        
        # Get content - prefer output_text if available (it's the combined text)
        if hasattr(response, 'output_text') and response.output_text:
            return response.output_text.strip(), tool_calls
        
        # Fallback: extract text from output items
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                item_type = getattr(item, 'type', None)
                
                # Skip function calls and reasoning
                if item_type in ('function_call', 'reasoning'):
                    continue
                
                # Handle message content
                if item_type == 'message':
                    if hasattr(item, 'content') and item.content:
                        for content_item in item.content:
                            text = None
                            # Get text from content item
                            if hasattr(content_item, 'text') and content_item.text:
                                text = content_item.text
                            elif isinstance(content_item, dict):
                                text = content_item.get('text', '')
                            elif isinstance(content_item, str):
                                text = content_item
                            
                            if text and text not in content_parts:
                                content_parts.append(text)
                
                # Handle direct text output
                elif item_type in ('text', 'output_text'):
                    text = getattr(item, 'text', '')
                    if text and text not in content_parts:
                        content_parts.append(text)
        
        content = ''.join(content_parts)
        return content.strip(), tool_calls
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a response using GPT-5 responses.create() API."""
        
        # Convert messages to GPT-5 format
        input_messages = self._convert_messages_to_input(messages)
        if not input_messages and messages:
            # Fallback to prevent empty input errors
            input_messages = [{
                "role": "user",
                "content": [{"type": "input_text", "text": str(messages)}]
            }]
        
        # Build base API parameters
        api_params = {
            "model": self.model,
            "input": input_messages,
            "text": {
                "format": {"type": "text"}
            },
        }

        runtime_params = normalize_model_params(
            self.model,
            {
                "reasoning_effort": self.reasoning_effort,
                "text_verbosity": self.verbosity,
                "reasoning_summary": self.summary,
                "max_output_tokens": self.max_output_tokens,
                "store": self.store,
                "parallel_tool_calls": self.parallel_tool_calls,
            },
            role="deep",
        )
        apply_responses_model_params(api_params, self.model, runtime_params, role="deep")
        reasoning_effort = runtime_params.get("reasoning_effort")
        runtime_verbosity = runtime_params.get("text_verbosity") or runtime_params.get("verbosity")

        print(
            f"[OPENAI RESPONSES] Model: {self.model}, "
            f"{describe_registry_model_params(self.model, runtime_params, role='deep')}"
        )
        input_chars = len(str(input_messages))

        def _usage_value(source: Any, key: str, default: int = 0) -> int:
            if source is None:
                return default
            if isinstance(source, dict):
                value = source.get(key, default)
            else:
                value = getattr(source, key, default)
            return int(value or 0)

        def _extract_usage_dict(resp) -> Dict[str, int]:
            usage_dict = {
                "input_tokens": 0,
                "cache_hit_tokens": 0,
                "cache_miss_tokens": 0,
                "cache_creation_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
            }
            usage = getattr(resp, "usage", None)
            if usage is None:
                return usage_dict

            for key in ("input_tokens", "output_tokens", "total_tokens"):
                usage_dict[key] = _usage_value(usage, key)

            input_details = (
                usage.get("input_tokens_details")
                if isinstance(usage, dict)
                else getattr(usage, "input_tokens_details", None)
            )
            output_details = (
                usage.get("output_tokens_details")
                if isinstance(usage, dict)
                else getattr(usage, "output_tokens_details", None)
            )
            cache_hit_tokens = _usage_value(input_details, "cached_tokens")
            cache_creation_tokens = _usage_value(input_details, "cache_creation")
            usage_dict["cache_hit_tokens"] = cache_hit_tokens
            usage_dict["cache_creation_tokens"] = cache_creation_tokens
            usage_dict["cache_miss_tokens"] = max(
                usage_dict["input_tokens"] - cache_hit_tokens - cache_creation_tokens,
                0,
            )
            usage_dict["reasoning_tokens"] = _usage_value(output_details, "reasoning_tokens")

            if usage_dict["total_tokens"] == 0:
                usage_dict["total_tokens"] = usage_dict["input_tokens"] + usage_dict["output_tokens"]
            return usage_dict

        def _record_llm_call(
            *,
            status: str,
            latency_seconds: float,
            output_chars: int,
            usage: Dict[str, int] | None = None,
            error_message: str | None = None,
        ) -> None:
            payload = {
                "model": self.model,
                "purpose": "gpt5_responses",
                "model_role": self.model_role,
                "status": status,
                "latency_seconds": round(float(latency_seconds), 4),
                "input_chars": input_chars,
                "output_chars": int(output_chars or 0),
                "effort": reasoning_effort,
                "verbosity": runtime_verbosity,
                "usage": usage or {},
                "error_message": error_message,
            }

            logged_to_state = False
            try:
                from webui.utils.state import app_state

                app_state.register_llm_call(
                    model_name=self.model,
                    purpose="gpt5_responses",
                    latency_seconds=payload["latency_seconds"],
                    input_chars=payload["input_chars"],
                    output_chars=payload["output_chars"],
                    effort=payload["effort"],
                    verbosity=payload["verbosity"],
                    usage=payload["usage"],
                    status=status,
                    error_message=error_message,
                )
                logged_to_state = True
            except Exception:
                pass

            if not logged_to_state:
                try:
                    from tradingagents.run_logger import get_run_audit_logger
                    get_run_audit_logger().log_event(event_type="llm_call", payload=payload)
                except Exception:
                    pass
        
        # Handle tool calls if present
        tools = kwargs.get("tools", [])
        if tools:
            # Convert LangChain/Pydantic tools to OpenAI Responses function-tool format.
            openai_tools = []
            for tool in tools:
                tool_schema = self._to_responses_function_tool(tool)
                if tool_schema:
                    openai_tools.append(tool_schema)
            
            if openai_tools:
                api_params["tools"] = openai_tools
                tool_choice = self._normalize_tool_choice(kwargs.get("tool_choice"))
                if tool_choice:
                    api_params["tool_choice"] = tool_choice
        
        try:
            # Make the API call
            call_started = time.time()
            response = self._client.responses.create(**api_params)
            latency_seconds = time.time() - call_started
            
            # Debug: Print response structure
            if hasattr(response, 'output') and response.output:
                print(f"[GPT5] Response has {len(response.output)} output items")
                for i, item in enumerate(response.output):
                    item_type = getattr(item, 'type', 'unknown')
                    print(f"[GPT5]   Item {i}: type={item_type}")
                    if item_type == 'function_call':
                        print(f"[GPT5]     Function: {getattr(item, 'name', 'unknown')}")
                    elif item_type == 'message':
                        # Debug: show message structure
                        if hasattr(item, 'content'):
                            print(f"[GPT5]     Message has content: {type(item.content)}")
                            if isinstance(item.content, list):
                                for j, c in enumerate(item.content):
                                    c_type = getattr(c, 'type', type(c).__name__)
                                    c_text = getattr(c, 'text', str(c)[:100] if c else 'None')
                                    print(f"[GPT5]       Content[{j}]: type={c_type}, text_len={len(c_text) if c_text else 0}")
                            elif isinstance(item.content, str):
                                print(f"[GPT5]       Content is string, len={len(item.content)}")
                        else:
                            print(f"[GPT5]     Message has no content attr, dir: {[a for a in dir(item) if not a.startswith('_')]}")
            
            # Extract content and tool calls
            content, tool_calls = self._extract_content_from_response(response)
            
            # Debug: Show extracted content
            if content:
                print(f"[GPT5] Extracted content: {len(content)} chars")
                print(f"[GPT5]   Content preview: {content[:200]}..." if len(content) > 200 else f"[GPT5]   Content: {content}")
            elif tool_calls:
                print(f"[GPT5] No text content; response contains tool calls only.")
            else:
                print(f"[GPT5] WARNING: No content extracted from response!")
                # Try to get output_text directly
                if hasattr(response, 'output_text') and response.output_text:
                    print(f"[GPT5]   But output_text exists: {len(response.output_text)} chars")
                    content = response.output_text
            
            if tool_calls:
                print(f"[GPT5] Found {len(tool_calls)} tool calls")
                for tc in tool_calls:
                    print(f"[GPT5]   Tool: {tc['function']['name']}")

            usage_dict = _extract_usage_dict(response)
            _record_llm_call(
                status="success",
                latency_seconds=latency_seconds,
                output_chars=len(content or ""),
                usage=usage_dict,
            )
            
            # Create the AI message
            additional_kwargs = {}
            if tool_calls:
                additional_kwargs["tool_calls"] = tool_calls
            
            # Also add tool_calls attribute for LangChain compatibility
            ai_message = AIMessage(
                content=content,
                additional_kwargs=additional_kwargs
            )
            ai_message.usage_metadata = {
                "input_tokens": usage_dict["input_tokens"],
                "output_tokens": usage_dict["output_tokens"],
                "total_tokens": usage_dict["total_tokens"],
                "input_token_details": {
                    "cache_read": usage_dict["cache_hit_tokens"],
                    "cache_creation": usage_dict["cache_creation_tokens"],
                },
                "output_token_details": {
                    "reasoning": usage_dict["reasoning_tokens"],
                },
            }
            
            # Set tool_calls attribute directly for better compatibility
            if tool_calls:
                ai_message.tool_calls = [
                    {
                        "name": tc["function"]["name"],
                        "args": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"],
                        "id": tc["id"],
                        "type": "tool_call"
                    }
                    for tc in tool_calls
                ]
            
            generation = ChatGeneration(message=ai_message)
            return ChatResult(generations=[generation])
            
        except Exception as e:
            # Return error as content
            error_message = f"Error calling GPT-5 API: {str(e)}"
            print(f"[GPT5] {error_message}")
            latency_seconds = 0.0
            try:
                latency_seconds = max(0.0, time.time() - call_started)
            except Exception:
                pass
            _record_llm_call(
                status="error",
                latency_seconds=latency_seconds,
                output_chars=len(error_message),
                usage={},
                error_message=error_message,
            )
            ai_message = AIMessage(content=error_message)
            generation = ChatGeneration(message=ai_message)
            return ChatResult(generations=[generation])
    
    def bind_tools(self, tools: List[Any], **kwargs) -> "GPT5ChatModel":
        """Bind tools to the model for function calling."""
        # Create a new instance with tools stored
        new_model = GPT5ChatModel(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            reasoning_effort=self.reasoning_effort,
            verbosity=self.verbosity,
            summary=self.summary,
            max_output_tokens=self.max_output_tokens,
            store=self.store,
            parallel_tool_calls=self.parallel_tool_calls,
            model_role=self.model_role,
        )
        new_model._bound_tools = tools
        if "tool_choice" in kwargs:
            new_model._bound_tool_choice = kwargs["tool_choice"]
        return new_model
    
    def invoke(self, input: Any, config: Optional[Dict] = None, **kwargs) -> AIMessage:
        """Invoke the model with input."""
        # Handle string input
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        elif isinstance(input, list):
            messages = input
        else:
            messages = [HumanMessage(content=str(input))]
        
        # Add bound tools if present
        if hasattr(self, '_bound_tools'):
            kwargs['tools'] = self._bound_tools
            if hasattr(self, '_bound_tool_choice'):
                kwargs.setdefault('tool_choice', self._bound_tool_choice)
        
        result = self._generate(messages, **kwargs)
        return result.generations[0].message


def is_gpt5_model(model_name: str) -> bool:
    """Check if core chat calls should use the Responses API wrapper."""
    return is_responses_model(model_name)


def get_chat_model(model_name: str, api_key: Optional[str] = None, **kwargs):
    """Factory function to get the appropriate chat model."""
    base_url = kwargs.pop("base_url", None)
    model_role = kwargs.pop("model_role", "deep")

    if is_responses_model(model_name):
        params = normalize_model_params(model_name, kwargs, role=model_role)
        reasoning_effort = params.get("reasoning_effort", "medium")
        verbosity = params.get("text_verbosity") or params.get("verbosity", "medium")
        summary = params.get("reasoning_summary") or params.get("summary", "auto")
        max_output_tokens = params.get("max_output_tokens")
        store = bool(params.get("store", False))
        parallel_tool_calls = bool(params.get("parallel_tool_calls", True))
        
        return GPT5ChatModel(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            summary=summary,
            max_output_tokens=max_output_tokens,
            store=store,
            parallel_tool_calls=parallel_tool_calls,
            model_role=model_role,
        )
    else:
        from langchain_openai import ChatOpenAI
        # Chat Completions uses max_tokens; the UI uses max_output_tokens.
        if "max_output_tokens" in kwargs and "max_tokens" not in kwargs:
            kwargs["max_tokens"] = kwargs.pop("max_output_tokens")
        for unsupported in (
            "reasoning_effort",
            "text_verbosity",
            "verbosity",
            "reasoning_summary",
            "summary",
            "store",
            "parallel_tool_calls",
        ):
            kwargs.pop(unsupported, None)
        chat_kwargs = {"model": model_name, **kwargs}
        if api_key is not None:
            chat_kwargs["openai_api_key"] = api_key
        if base_url:
            chat_kwargs["openai_api_base"] = base_url
        return ChatOpenAI(**chat_kwargs)

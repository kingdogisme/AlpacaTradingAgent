"""Provider-agnostic LLM client package.

Keep this package cheap to import. CLI navigation and model catalog code should
not require LangChain provider packages until an actual LLM client is created.
"""

from __future__ import annotations


def create_llm_client(*args, **kwargs):
    from .factory import create_llm_client as _create_llm_client

    return _create_llm_client(*args, **kwargs)


def __getattr__(name: str):
    if name == "BaseLLMClient":
        from .base_client import BaseLLMClient

        return BaseLLMClient
    raise AttributeError(name)


__all__ = ["BaseLLMClient", "create_llm_client"]

"""Dynamic provider model discovery for CLI and Web UI selectors."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import requests

ModelOption = Tuple[str, str]


class ModelDiscoveryError(RuntimeError):
    """Raised when a provider model scan fails."""


def normalize_google_base_url(base_url: Optional[str]) -> Optional[str]:
    """Normalize Gemini-compatible base URLs to provider root."""
    if not base_url:
        return base_url

    normalized = base_url.rstrip("/")
    for suffix in ("/v1beta", "/v1"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _require_api_key(provider: str, env_names: list[str]) -> str:
    for env_name in env_names:
        value = os.getenv(env_name)
        if value:
            return value
    raise ModelDiscoveryError(
        f"Missing API key for provider '{provider}'. Expected one of: {', '.join(env_names)}"
    )


def _request_json(method: str, url: str, **kwargs):
    try:
        response = requests.request(method, url, timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        body = exc.response.text[:500] if exc.response is not None else str(exc)
        raise ModelDiscoveryError(
            f"HTTP {exc.response.status_code if exc.response else '?'} from {url}: {body}"
        ) from exc
    except requests.RequestException as exc:
        raise ModelDiscoveryError(f"Request to {url} failed: {exc}") from exc
    except ValueError as exc:
        raise ModelDiscoveryError(f"Invalid JSON returned by {url}") from exc


def _discover_openai_compatible_models(base_url: str, api_key: Optional[str]) -> List[ModelOption]:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = _request_json("GET", f"{base_url.rstrip('/')}/models", headers=headers)
    models = payload.get("data") or []
    if not models:
        raise ModelDiscoveryError("Provider returned no models.")

    discovered = []
    for item in models:
        model_id = item.get("id")
        if not model_id:
            continue
        discovered.append((item.get("name") or model_id, model_id))

    if not discovered:
        raise ModelDiscoveryError("Provider returned no usable model ids.")

    return sorted(discovered, key=lambda pair: pair[1])


def _discover_google_models(base_url: str, api_key: str) -> List[ModelOption]:
    normalized = normalize_google_base_url(base_url)
    if not normalized:
        raise ModelDiscoveryError("Google provider requires a base URL.")

    payload = _request_json(
        "GET",
        f"{normalized.rstrip('/')}/v1beta/models",
        params={"key": api_key},
    )
    models = payload.get("models") or []
    if not models:
        raise ModelDiscoveryError("Provider returned no Gemini models.")

    discovered = []
    for item in models:
        name = item.get("name", "")
        if not name:
            continue
        model_id = name.split("models/", 1)[-1]
        display = item.get("displayName") or model_id
        discovered.append((display, model_id))

    if not discovered:
        raise ModelDiscoveryError("Provider returned no usable Gemini model ids.")

    return sorted(discovered, key=lambda pair: pair[1])


def _discover_ollama_models(base_url: str) -> List[ModelOption]:
    api_root = base_url.rstrip("/")
    if api_root.endswith("/v1"):
        api_root = api_root[: -len("/v1")]
    payload = _request_json("GET", f"{api_root}/api/tags")
    models = payload.get("models") or []
    if not models:
        raise ModelDiscoveryError("Ollama returned no local models.")

    discovered = []
    for item in models:
        model_id = item.get("model") or item.get("name")
        if not model_id:
            continue
        discovered.append((item.get("name") or model_id, model_id))

    if not discovered:
        raise ModelDiscoveryError("Ollama returned no usable model ids.")

    return sorted(discovered, key=lambda pair: pair[1])


def discover_models(provider: str, base_url: Optional[str] = None) -> List[ModelOption]:
    """Discover available models for a provider."""
    provider_lower = (provider or "").lower()

    if provider_lower == "google":
        api_key = _require_api_key("google", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
        return _discover_google_models(
            base_url or os.getenv("TRADINGAGENTS_GOOGLE_BASE_URL") or "https://generativelanguage.googleapis.com",
            api_key,
        )

    if provider_lower == "openai":
        api_key = _require_api_key("openai", ["OPENAI_API_KEY"])
        return _discover_openai_compatible_models(
            base_url or os.getenv("TRADINGAGENTS_BACKEND_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            api_key,
        )

    if provider_lower == "local_openai":
        api_key = os.getenv("OPENAI_API_KEY") or "local-llm"
        return _discover_openai_compatible_models(
            base_url or os.getenv("TRADINGAGENTS_BACKEND_URL") or os.getenv("OPENAI_BASE_URL") or "http://localhost:11434/v1",
            api_key,
        )

    if provider_lower in {"xai", "deepseek", "qwen", "glm", "openrouter"}:
        env_map = {
            "xai": ["XAI_API_KEY"],
            "deepseek": ["DEEPSEEK_API_KEY"],
            "qwen": ["DASHSCOPE_API_KEY"],
            "glm": ["ZHIPU_API_KEY"],
            "openrouter": ["OPENROUTER_API_KEY"],
        }
        default_base = {
            "xai": "https://api.x.ai/v1",
            "deepseek": "https://api.deepseek.com",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "glm": "https://open.bigmodel.cn/api/paas/v4",
            "openrouter": "https://openrouter.ai/api/v1",
        }
        api_key = _require_api_key(provider_lower, env_map[provider_lower])
        return _discover_openai_compatible_models(
            base_url or default_base[provider_lower],
            api_key,
        )

    if provider_lower == "ollama":
        return _discover_ollama_models(base_url or "http://localhost:11434")

    raise ModelDiscoveryError(
        f"Dynamic model discovery is not implemented for provider '{provider_lower}'."
    )

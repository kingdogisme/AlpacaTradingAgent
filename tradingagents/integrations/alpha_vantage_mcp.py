from __future__ import annotations

import json
from typing import Any

import requests

from tradingagents.integrations.sellthenews import decode_mcp_response, extract_text


class AlphaVantageMCPError(Exception):
    """Base Alpha Vantage MCP integration error."""


class AlphaVantageMCPUnavailable(AlphaVantageMCPError):
    """Raised when Alpha Vantage MCP is unavailable or rate-limited."""


class AlphaVantageMCPBadResponse(AlphaVantageMCPError):
    """Raised when Alpha Vantage MCP returns an unreadable payload."""


UNAVAILABLE_MARKERS = (
    "standard api rate limit",
    "rate limit",
    "please consider spreading out your free api requests",
    "premium plans",
    "invalid api call",
    "error message",
)


class AlphaVantageMCPClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 8.0):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        tool_call_arguments = {
            "tool_name": tool_name,
            "arguments": json.dumps(arguments or {}, ensure_ascii=False),
        }
        data = self._mcp_call("TOOL_CALL", tool_call_arguments)
        if data.get("error"):
            raise AlphaVantageMCPUnavailable(str(data["error"]))

        text = extract_text(data.get("result")).strip()
        if not text:
            raise AlphaVantageMCPBadResponse("response contained no readable content")
        if looks_unavailable(text):
            raise AlphaVantageMCPUnavailable(text[:300])
        return text

    def _mcp_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self._url(),
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AlphaVantageMCPUnavailable(str(exc)) from exc

        if response.status_code != 200:
            raise AlphaVantageMCPUnavailable(f"HTTP {response.status_code}: {response.text[:300]}")

        data = decode_mcp_response(response)
        if not isinstance(data, dict):
            raise AlphaVantageMCPBadResponse("response root must be an object")
        return data

    def _url(self) -> str:
        separator = "&" if "?" in self.base_url else "?"
        return f"{self.base_url}{separator}apikey={self.api_key}"


def looks_unavailable(text: Any) -> bool:
    body = " ".join(str(text or "").split()).lower()
    return any(marker in body for marker in UNAVAILABLE_MARKERS)

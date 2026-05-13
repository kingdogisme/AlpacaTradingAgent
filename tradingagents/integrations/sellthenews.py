from __future__ import annotations

import json
from typing import Any

import requests


class SellTheNewsError(Exception):
    """Base SellTheNews integration error."""


class SellTheNewsUnavailable(SellTheNewsError):
    """Raised when SellTheNews is unavailable or returns an MCP error."""


class SellTheNewsBadResponse(SellTheNewsError):
    """Raised when SellTheNews returns an invalid or unreadable payload."""


SPARSE_MARKERS = (
    "total articles: 0",
    "no articles found",
    "returned 0 articles",
    "0 articles found",
    "no company-specific articles",
    "no news found",
    "sample count: 0",
)


class SellTheNewsClient:
    def __init__(self, base_url: str, timeout_seconds: float = 8.0):
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise SellTheNewsUnavailable(str(exc)) from exc

        if response.status_code != 200:
            raise SellTheNewsUnavailable(f"HTTP {response.status_code}: {response.text[:300]}")

        data = decode_mcp_response(response)
        if not isinstance(data, dict):
            raise SellTheNewsBadResponse("response root must be an object")
        if data.get("error"):
            raise SellTheNewsUnavailable(str(data["error"]))

        text = extract_text(data.get("result"))
        if not text.strip():
            raise SellTheNewsBadResponse("response contained no readable content")
        return text.strip()


def decode_mcp_response(response: requests.Response) -> dict[str, Any]:
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.text.strip()

    if "text/event-stream" in content_type:
        events: list[str] = []
        current_event: list[str] = []
        for line in body.splitlines():
            if not line.strip():
                if current_event:
                    events.append("\n".join(current_event))
                    current_event = []
                continue
            if line.startswith("data:"):
                current_event.append(line[len("data:") :].strip())
            elif current_event and not line.startswith(("event:", "id:", "retry:")):
                # Some SellTheNews responses include literal newlines inside a
                # single JSON data payload instead of prefixing every continued
                # SSE data line with `data:`. Preserve those continuation lines
                # so long article bodies still decode as one JSON object.
                current_event.append(line)
        if current_event:
            events.append("\n".join(current_event))
        if not events:
            raise SellTheNewsBadResponse("event-stream response contained no data payload")
        parse_error: ValueError | None = None
        for raw in events:
            if not raw or raw == "[DONE]":
                continue
            try:
                decoded = json.loads(raw)
            except ValueError as exc:
                parse_error = exc
                continue
            if not isinstance(decoded, dict):
                raise SellTheNewsBadResponse("event-stream payload root must be an object")
            return decoded
        raise SellTheNewsBadResponse("event-stream payload was not valid JSON") from parse_error

    try:
        decoded = response.json()
    except ValueError as exc:
        raise SellTheNewsBadResponse("response was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SellTheNewsBadResponse("response root must be an object")
    return decoded


def extract_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if "content" in result and isinstance(result.get("content"), list):
            parts: list[str] = []
            for item in result["content"]:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif "json" in item:
                        parts.append(json.dumps(item["json"], ensure_ascii=False, indent=2))
            return "\n\n".join(part.strip() for part in parts if str(part).strip())
        if isinstance(result.get("structuredContent"), (dict, list)):
            return json.dumps(result["structuredContent"], ensure_ascii=False, indent=2)
        if isinstance(result.get("text"), str):
            return result["text"]
        return ""
    if isinstance(result, list):
        return "\n\n".join(part for part in (extract_text(item).strip() for item in result) if part)
    return str(result)


def looks_sparse(text: Any, *, min_chars: int = 220) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if any(marker in lowered for marker in SPARSE_MARKERS):
        return True
    return len(normalized) < min_chars

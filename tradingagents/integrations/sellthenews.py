from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

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

    def _site_origin(self) -> str:
        parsed = urlparse(self.base_url)
        if not parsed.scheme or not parsed.netloc:
            raise SellTheNewsUnavailable("SellTheNews base URL is invalid")
        host = parsed.netloc
        if host.startswith("mcp."):
            host = host[len("mcp.") :]
        return urlunparse((parsed.scheme, host, "", "", "", ""))

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
        attempts = 2
        last_error: SellTheNewsError | None = None
        for attempt in range(attempts):
            try:
                response = requests.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = SellTheNewsUnavailable(str(exc))
                if attempt + 1 < attempts:
                    time.sleep(0.25)
                    continue
                raise last_error from exc

            if response.status_code != 200:
                last_error = SellTheNewsUnavailable(f"HTTP {response.status_code}: {response.text[:300]}")
                if attempt + 1 < attempts and response.status_code in {408, 429, 500, 502, 503, 504}:
                    time.sleep(0.25)
                    continue
                raise last_error

            try:
                data = decode_mcp_response(response)
            except SellTheNewsBadResponse as exc:
                excerpt = " ".join(response.text.split())[:500]
                last_error = SellTheNewsBadResponse(f"{exc}; raw_excerpt={excerpt!r}")
                if attempt + 1 < attempts:
                    time.sleep(0.25)
                    continue
                raise last_error from exc

            if not isinstance(data, dict):
                raise SellTheNewsBadResponse("response root must be an object")
            if data.get("error"):
                raise SellTheNewsUnavailable(str(data["error"]))

            text = extract_text(data.get("result"))
            if not text.strip():
                last_error = SellTheNewsBadResponse("response contained no readable content")
                if attempt + 1 < attempts:
                    time.sleep(0.25)
                    continue
                raise last_error
            return text.strip()

        raise last_error or SellTheNewsUnavailable("SellTheNews request failed")

    def get_options_chain(
        self,
        ticker: str,
        *,
        expiration: str | None = None,
        greeks: str = "gamma",
    ) -> dict[str, Any]:
        """Fetch the SellTheNews options-chain JSON used by the dashboard."""
        api_url = f"{self._site_origin()}/api/options/chain"
        params: dict[str, str] = {"ticker": ticker, "greeks": greeks or "gamma"}
        if expiration:
            params["exp"] = expiration
        try:
            response = requests.get(
                f"{api_url}?{urlencode(params)}",
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise SellTheNewsUnavailable(str(exc)) from exc

        if response.status_code != 200:
            raise SellTheNewsUnavailable(f"HTTP {response.status_code}: {response.text[:300]}")

        try:
            data = response.json()
        except ValueError as exc:
            raise SellTheNewsBadResponse("options chain response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise SellTheNewsBadResponse("options chain response root must be an object")
        if data.get("ok") is False:
            raise SellTheNewsUnavailable(str(data.get("error") or "options chain request failed"))
        return data


def _escape_unescaped_control_chars_in_json_strings(text: str) -> str:
    """Return JSON text with raw control chars inside strings escaped.

    Some SellTheNews SSE responses arrive as one `data:` JSON payload but contain
    literal line breaks inside the nested MCP text field instead of JSON-escaped
    `\\n` sequences or repeated SSE `data:` continuation prefixes. The payload is
    still structurally recoverable: escaping only control characters observed
    while inside a JSON string restores valid JSON without changing delimiters.
    """
    out: list[str] = []
    in_string = False
    escaping = False
    for char in text:
        if escaping:
            out.append(char)
            escaping = False
            continue
        if char == "\\" and in_string:
            out.append(char)
            escaping = True
            continue
        if char == '"':
            out.append(char)
            in_string = not in_string
            continue
        if in_string and char == "\n":
            out.append("\\n")
            continue
        if in_string and char == "\r":
            out.append("\\r")
            continue
        if in_string and char == "\t":
            out.append("\\t")
            continue
        if in_string and ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
            continue
        out.append(char)
    return "".join(out)


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
        decoder = json.JSONDecoder()
        for raw in events:
            if not raw or raw == "[DONE]":
                continue
            candidates = [raw]
            first_brace = raw.find("{")
            if first_brace > 0:
                candidates.append(raw[first_brace:])
            last_brace = raw.rfind("}")
            if first_brace >= 0 and last_brace > first_brace:
                candidates.append(raw[first_brace : last_brace + 1])
            for candidate in candidates:
                parse_candidates = [candidate]
                escaped_candidate = _escape_unescaped_control_chars_in_json_strings(candidate)
                if escaped_candidate != candidate:
                    parse_candidates.append(escaped_candidate)
                decoded = None
                for parse_candidate in parse_candidates:
                    try:
                        decoded = json.loads(parse_candidate)
                        break
                    except ValueError as exc:
                        parse_error = exc
                        try:
                            decoded, _ = decoder.raw_decode(parse_candidate.lstrip())
                            break
                        except ValueError as raw_exc:
                            parse_error = raw_exc
                            decoded = None
                            continue
                if decoded is None:
                    continue
                if not isinstance(decoded, dict):
                    raise SellTheNewsBadResponse("event-stream payload root must be an object")
                if "result" in decoded or "error" in decoded or "method" in decoded:
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

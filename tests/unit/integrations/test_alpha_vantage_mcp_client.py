from __future__ import annotations

import json

import pytest

from tradingagents.integrations import alpha_vantage_mcp
from tradingagents.integrations.alpha_vantage_mcp import (
    AlphaVantageMCPClient,
    AlphaVantageMCPUnavailable,
    looks_unavailable,
)


class FakeResponse:
    def __init__(self, *, status_code=200, text="", headers=None, payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "application/json"}
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_tool_call_wraps_alpha_vantage_tool_call(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse(
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [
                        {"type": "text", "text": '{"Symbol": "NVDA", "PERatio": "42.1"}'}
                    ]
                },
            }
        )

    monkeypatch.setattr(alpha_vantage_mcp.requests, "post", fake_post)

    result = AlphaVantageMCPClient("https://example.invalid/mcp", "demo").call_tool(
        "COMPANY_OVERVIEW",
        {"symbol": "NVDA"},
    )

    assert "apikey=demo" in captured["url"]
    params = captured["json"]["params"]
    assert params["name"] == "TOOL_CALL"
    assert params["arguments"]["tool_name"] == "COMPANY_OVERVIEW"
    assert json.loads(params["arguments"]["arguments"]) == {"symbol": "NVDA"}
    assert "PERatio" in result


def test_rate_limit_message_raises_unavailable(monkeypatch):
    monkeypatch.setattr(
        alpha_vantage_mcp.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse(
            payload={
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "We have detected your API key and our standard API rate limit is 25 requests per day.",
                        }
                    ]
                }
            }
        ),
    )

    with pytest.raises(AlphaVantageMCPUnavailable):
        AlphaVantageMCPClient("https://example.invalid/mcp", "demo").call_tool(
            "EARNINGS",
            {"symbol": "NVDA"},
        )


def test_unavailable_detection():
    assert looks_unavailable("standard API rate limit is 25 requests per day")
    assert not looks_unavailable('{"Symbol": "NVDA", "RevenueTTM": "130497000000"}')

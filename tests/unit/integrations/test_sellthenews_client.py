from __future__ import annotations

import pytest

from tradingagents.integrations import sellthenews
from tradingagents.integrations.sellthenews import (
    SellTheNewsBadResponse,
    SellTheNewsClient,
    SellTheNewsUnavailable,
    decode_mcp_response,
    looks_sparse,
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


def test_json_response_parse(monkeypatch):
    def fake_post(*_args, **_kwargs):
        return FakeResponse(
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "NVDA article body"}]},
            }
        )

    monkeypatch.setattr(sellthenews.requests, "post", fake_post)

    result = SellTheNewsClient("https://example.invalid/mcp").call_tool(
        "get_stock_news",
        {"ticker": "NVDA"},
    )

    assert result == "NVDA article body"


def test_sse_response_parse():
    response = FakeResponse(
        text=(
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"live macro"}]}}\n\n'
        ),
        headers={"content-type": "text/event-stream"},
    )

    assert decode_mcp_response(response)["result"]["content"][0]["text"] == "live macro"


def test_sse_response_parse_with_unprefixed_continuation_lines():
    response = FakeResponse(
        text=(
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"first line\\n'
            'second line\\n'
            'third line"}]}}\n\n'
        ),
        headers={"content-type": "text/event-stream"},
    )

    text = decode_mcp_response(response)["result"]["content"][0]["text"]

    assert text == "first line\nsecond line\nthird line"


def test_http_error_raises_unavailable(monkeypatch):
    monkeypatch.setattr(
        sellthenews.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse(status_code=503, text="down"),
    )

    with pytest.raises(SellTheNewsUnavailable):
        SellTheNewsClient("https://example.invalid/mcp").call_tool("get_live_news", {})


def test_mcp_error_raises_unavailable(monkeypatch):
    monkeypatch.setattr(
        sellthenews.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse(payload={"error": {"message": "bad tool"}}),
    )

    with pytest.raises(SellTheNewsUnavailable):
        SellTheNewsClient("https://example.invalid/mcp").call_tool("missing_tool", {})


def test_empty_or_malformed_response_raises_bad_response(monkeypatch):
    monkeypatch.setattr(
        sellthenews.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse(payload={"result": {"content": []}}),
    )

    with pytest.raises(SellTheNewsBadResponse):
        SellTheNewsClient("https://example.invalid/mcp").call_tool("get_live_news", {})


def test_structured_content_and_sparse_detection():
    response = FakeResponse(payload={"result": {"structuredContent": {"articles": []}}})
    text = sellthenews.extract_text(decode_mcp_response(response)["result"])

    assert '"articles": []' in text
    assert looks_sparse("Total articles: 0")
    assert looks_sparse("short")
    assert not looks_sparse("market catalyst " * 40)

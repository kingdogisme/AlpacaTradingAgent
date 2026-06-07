from __future__ import annotations

import json

import pytest

from tradingagents.integrations import robinhood_mcp
from tradingagents.integrations.robinhood_mcp import (
    RobinhoodMCPAuthError,
    RobinhoodMCPClient,
    RobinhoodPKCEFlow,
    exchange_oauth_callback,
    start_oauth_flow,
    token_is_expiring,
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


def test_oauth_flow_uses_pkce_and_resource(monkeypatch):
    monkeypatch.setattr(robinhood_mcp, "register_oauth_client", lambda _config: "client-1")

    flow = start_oauth_flow(robinhood_mcp.RobinhoodOAuthConfig(redirect_uri="http://127.0.0.1:8765/cb"))

    assert "client_id=client-1" in flow.authorization_url
    assert "code_challenge_method=S256" in flow.authorization_url
    assert "resource=https%3A%2F%2Fagent.robinhood.com%2Fmcp%2Ftrading" in flow.authorization_url
    assert flow.redirect_uri == "http://127.0.0.1:8765/cb"


def test_exchange_callback_rejects_state_mismatch():
    flow = RobinhoodPKCEFlow(
        authorization_url="https://robinhood.com/oauth",
        state="expected",
        code_verifier="verifier",
        client_id="client-1",
        redirect_uri="http://127.0.0.1:8765/cb",
        scope="internal",
        mcp_url="https://agent.robinhood.com/mcp/trading",
        token_endpoint="https://api.robinhood.com/oauth2/token/",
    )

    with pytest.raises(RobinhoodMCPAuthError):
        exchange_oauth_callback("http://127.0.0.1:8765/cb?code=abc&state=wrong", flow)


def test_client_initializes_and_extracts_quote_payload(monkeypatch):
    calls = []

    def fake_post(_url, **kwargs):
        calls.append(kwargs["json"])
        method = kwargs["json"].get("method")
        if method == "initialize":
            return FakeResponse(
                headers={"content-type": "text/event-stream", "Mcp-Session-Id": "session-1"},
                text='event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"robinhood-trading"}}}\n\n',
            )
        if method == "notifications/initialized":
            return FakeResponse(status_code=202, text="", headers={})
        return FakeResponse(
            headers={"content-type": "application/json"},
            text=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "data": {
                                            "results": [
                                                {
                                                    "quote": {
                                                        "symbol": "NVDA",
                                                        "last_trade_price": "205.11",
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ),
                            }
                        ]
                    },
                }
            ),
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "data": {
                                        "results": [
                                            {
                                                "quote": {
                                                    "symbol": "NVDA",
                                                    "last_trade_price": "205.11",
                                                }
                                            }
                                        ]
                                    }
                                }
                            ),
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(robinhood_mcp.requests, "post", fake_post)

    quote = RobinhoodMCPClient(access_token="token").get_equity_quote("NVDA")

    assert quote["quote"]["symbol"] == "NVDA"
    assert calls[0]["method"] == "initialize"
    assert calls[-1]["params"]["name"] == "get_equity_quotes"
    assert calls[-1]["params"]["arguments"] == {"symbols": ["NVDA"]}


def test_token_expiry_uses_obtained_at():
    assert token_is_expiring({"obtained_at": 1000, "expires_in": 60}, skew_seconds=300)
    assert not token_is_expiring({"access_token": "token"})

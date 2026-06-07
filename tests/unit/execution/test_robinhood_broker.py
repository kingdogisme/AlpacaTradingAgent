from __future__ import annotations

from tradingagents.execution import BrokerRouter, create_broker_adapter
from tradingagents.execution.robinhood_broker import RobinhoodBrokerAdapter


def test_create_broker_adapter_supports_robinhood():
    adapter = create_broker_adapter(
        {
            "broker_adapter": "robinhood",
            "robinhood_mcp_token_path": "/tmp/token.json",
            "robinhood_mcp_dry_run": True,
        }
    )

    assert isinstance(adapter, RobinhoodBrokerAdapter)
    assert adapter.token_path == "/tmp/token.json"
    assert adapter.dry_run is True


def test_broker_router_selects_symbol_route_and_passes_dry_run():
    calls = []

    class FakeBroker:
        def execute_trading_action(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "dry_run": kwargs["dry_run"]}

    router = BrokerRouter(
        config={"broker_routes": {"default": "alpaca", "symbols": {"NVDA": "robinhood"}}},
        adapters={"robinhood": FakeBroker()},
    )

    result = router.execute_trading_action(
        symbol="NVDA",
        current_position="NEUTRAL",
        signal="BUY",
        dollar_amount=100,
        dry_run=True,
    )

    assert result["broker_name"] == "robinhood"
    assert result["dry_run"] is True
    assert calls[0]["symbol"] == "NVDA"


def test_robinhood_broker_dry_run_reviews_without_place(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def get_accounts(self):
            return [
                {
                    "account_number": "123456789",
                    "state": "active",
                    "agentic_allowed": True,
                }
            ]

        def review_equity_order(self, arguments):
            calls.append(("review", arguments))
            return {"estimated_total": "100.00"}

        def place_equity_order(self, arguments):
            calls.append(("place", arguments))
            return {"order_id": "order-1"}

    monkeypatch.setattr("tradingagents.execution.robinhood_broker.RobinhoodMCPClient", FakeClient)

    result = RobinhoodBrokerAdapter(token_path="/tmp/token.json", dry_run=True).execute_trading_action(
        symbol="NVDA",
        current_position="NEUTRAL",
        signal="BUY",
        dollar_amount=100,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["order_request"]["account_number"] == "****6789"
    assert result["order_request"]["dollar_amount"] == "100"
    assert ("place", result["order_request"]) not in calls
    assert calls[1][0] == "review"
    assert calls[1][1]["account_number"] == "123456789"
    assert calls[1][1]["dollar_amount"] == "100"


def test_robinhood_broker_requires_agentic_account(monkeypatch):
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def get_accounts(self):
            return [{"account_number": "123", "state": "active", "agentic_allowed": False}]

    monkeypatch.setattr("tradingagents.execution.robinhood_broker.RobinhoodMCPClient", FakeClient)

    result = RobinhoodBrokerAdapter(token_path="/tmp/token.json").execute_trading_action(
        symbol="NVDA",
        current_position="NEUTRAL",
        signal="BUY",
        dollar_amount=100,
    )

    assert result["success"] is False
    assert "agentic" in result["error"]


def test_robinhood_broker_blocks_live_orders_unless_enabled(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def get_accounts(self):
            return [{"account_number": "123456789", "state": "active", "agentic_allowed": True}]

        def review_equity_order(self, arguments):
            calls.append(("review", arguments))
            return {"estimated_total": "100.00"}

        def place_equity_order(self, arguments):
            calls.append(("place", arguments))
            return {"order_id": "order-1"}

    monkeypatch.setattr("tradingagents.execution.robinhood_broker.RobinhoodMCPClient", FakeClient)

    blocked = RobinhoodBrokerAdapter(token_path="/tmp/token.json", dry_run=False).execute_trading_action(
        symbol="NVDA",
        current_position="NEUTRAL",
        signal="BUY",
        dollar_amount=100,
        dry_run=False,
    )
    allowed = RobinhoodBrokerAdapter(
        token_path="/tmp/token.json",
        dry_run=False,
        live_orders_enabled=True,
    ).execute_trading_action(
        symbol="NVDA",
        current_position="NEUTRAL",
        signal="BUY",
        dollar_amount=100,
        dry_run=False,
    )

    assert blocked["success"] is False
    assert "disabled" in blocked["error"]
    assert allowed["success"] is True
    assert allowed["order"]["order_id"] == "order-1"
    assert [name for name, _ in calls] == ["review", "review", "place"]

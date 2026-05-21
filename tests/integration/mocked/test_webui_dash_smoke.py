from __future__ import annotations


def test_dash_webui_homepage_serves_with_test_client():
    from webui.app_dash import create_app

    app = create_app(base_path="/")
    response = app.server.test_client().get("/")

    assert response.status_code == 200
    assert b"TradingAgents" in response.data

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.integrations.robinhood_mcp import RobinhoodMCPAuthError
from tradingagents.integrations.robinhood_mcp import RobinhoodPKCEFlow


runner = CliRunner()


def test_robinhood_login_start_outputs_authorization_url(monkeypatch, tmp_path):
    flow = RobinhoodPKCEFlow(
        authorization_url="https://robinhood.com/oauth?client_id=client-1",
        state="state-1",
        code_verifier="verifier",
        client_id="client-1",
        redirect_uri="http://127.0.0.1:8765/cb",
        scope="internal",
        mcp_url="https://agent.robinhood.com/mcp/trading",
        token_endpoint="https://api.robinhood.com/oauth2/token/",
    )
    monkeypatch.setattr("cli.commands.robinhood.start_oauth_flow", lambda _config: flow)

    result = runner.invoke(
        app,
        [
            "robinhood-login",
            "--token-path",
            str(tmp_path / "token.json"),
            "--pending-path",
            str(tmp_path / "pending.json"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "authorization_required"
    assert payload["authorization_url"] == flow.authorization_url
    assert (tmp_path / "pending.json").exists()


def test_robinhood_login_callback_stores_token(monkeypatch, tmp_path):
    flow = RobinhoodPKCEFlow(
        authorization_url="https://robinhood.com/oauth?client_id=client-1",
        state="state-1",
        code_verifier="verifier",
        client_id="client-1",
        redirect_uri="http://127.0.0.1:8765/cb",
        scope="internal",
        mcp_url="https://agent.robinhood.com/mcp/trading",
        token_endpoint="https://api.robinhood.com/oauth2/token/",
    )
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(flow.to_dict()), encoding="utf-8")
    monkeypatch.setattr(
        "cli.commands.robinhood.exchange_oauth_callback",
        lambda _url, flow: {"access_token": "access", "refresh_token": "refresh", "client_id": flow.client_id},
    )

    result = runner.invoke(
        app,
        [
            "robinhood-login",
            "--callback-url",
            "http://127.0.0.1:8765/cb?code=abc&state=state-1",
            "--token-path",
            str(tmp_path / "token.json"),
            "--pending-path",
            str(pending),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "authenticated"
    stored = json.loads((tmp_path / "token.json").read_text(encoding="utf-8"))
    assert stored["refresh_token"] == "refresh"
    assert not pending.exists()


def test_robinhood_login_listen_waits_and_stores_token(monkeypatch, tmp_path):
    flow = RobinhoodPKCEFlow(
        authorization_url="https://robinhood.com/oauth?client_id=client-1",
        state="state-1",
        code_verifier="verifier",
        client_id="client-1",
        redirect_uri="http://127.0.0.1:8765/cb",
        scope="internal",
        mcp_url="https://agent.robinhood.com/mcp/trading",
        token_endpoint="https://api.robinhood.com/oauth2/token/",
    )
    monkeypatch.setattr("cli.commands.robinhood.start_oauth_flow", lambda _config: flow)
    monkeypatch.setattr(
        "cli.commands.robinhood.wait_for_oauth_callback",
        lambda _redirect_uri, timeout_seconds: "http://127.0.0.1:8765/cb?code=abc&state=state-1",
    )
    monkeypatch.setattr(
        "cli.commands.robinhood.exchange_oauth_callback",
        lambda _url, flow: {"access_token": "access", "refresh_token": "refresh", "client_id": flow.client_id},
    )

    result = runner.invoke(
        app,
        [
            "robinhood-login",
            "--listen",
            "--token-path",
            str(tmp_path / "token.json"),
            "--pending-path",
            str(tmp_path / "pending.json"),
        ],
    )

    assert result.exit_code == 0
    assert '"status": "waiting_for_callback"' in result.stdout
    assert '"status": "authenticated"' in result.stdout
    stored = json.loads((tmp_path / "token.json").read_text(encoding="utf-8"))
    assert stored["access_token"] == "access"


def test_robinhood_probe_reports_auth_error_without_traceback(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def get_equity_quote(self, _ticker):
            raise RobinhoodMCPAuthError("token file not found")

    monkeypatch.setattr("cli.commands.robinhood.RobinhoodMCPClient", FakeClient)

    result = runner.invoke(
        app,
        ["robinhood-probe", "--ticker", "NVDA", "--token-path", str(tmp_path / "missing.json")],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["next_command"] == "python3 -m cli.main robinhood-login"

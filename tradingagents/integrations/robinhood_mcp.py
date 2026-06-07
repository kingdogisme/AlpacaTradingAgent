from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from tradingagents.integrations.sellthenews import decode_mcp_response


DEFAULT_MCP_URL = "https://agent.robinhood.com/mcp/trading"
DEFAULT_AUTHORIZATION_ENDPOINT = "https://robinhood.com/oauth"
DEFAULT_REGISTRATION_ENDPOINT = "https://agent.robinhood.com/oauth/trading/register"
DEFAULT_TOKEN_ENDPOINT = "https://api.robinhood.com/oauth2/token/"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/oauth/callback"
DEFAULT_SCOPE = "internal"


class RobinhoodMCPError(Exception):
    """Base Robinhood MCP integration error."""


class RobinhoodMCPAuthError(RobinhoodMCPError):
    """Raised for OAuth and bearer-token failures."""


class RobinhoodMCPUnavailable(RobinhoodMCPError):
    """Raised when the Robinhood MCP endpoint is unavailable."""


class RobinhoodMCPBadResponse(RobinhoodMCPError):
    """Raised when the Robinhood MCP response cannot be decoded."""


def default_token_path() -> Path:
    return Path("~/.tradingagents/robinhood/oauth_token.json").expanduser()


@dataclass(frozen=True)
class RobinhoodOAuthConfig:
    mcp_url: str = DEFAULT_MCP_URL
    authorization_endpoint: str = DEFAULT_AUTHORIZATION_ENDPOINT
    registration_endpoint: str = DEFAULT_REGISTRATION_ENDPOINT
    token_endpoint: str = DEFAULT_TOKEN_ENDPOINT
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scope: str = DEFAULT_SCOPE
    client_name: str = "AlpacaTradingAgent"
    client_id: str | None = None


@dataclass(frozen=True)
class RobinhoodPKCEFlow:
    authorization_url: str
    state: str
    code_verifier: str
    client_id: str
    redirect_uri: str
    scope: str
    mcp_url: str
    token_endpoint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_url": self.authorization_url,
            "state": self.state,
            "code_verifier": self.code_verifier,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "mcp_url": self.mcp_url,
            "token_endpoint": self.token_endpoint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RobinhoodPKCEFlow":
        return cls(
            authorization_url=str(data["authorization_url"]),
            state=str(data["state"]),
            code_verifier=str(data["code_verifier"]),
            client_id=str(data["client_id"]),
            redirect_uri=str(data["redirect_uri"]),
            scope=str(data.get("scope") or DEFAULT_SCOPE),
            mcp_url=str(data.get("mcp_url") or DEFAULT_MCP_URL),
            token_endpoint=str(data.get("token_endpoint") or DEFAULT_TOKEN_ENDPOINT),
        )


def start_oauth_flow(config: RobinhoodOAuthConfig) -> RobinhoodPKCEFlow:
    client_id = config.client_id or register_oauth_client(config)
    code_verifier = _token_urlsafe_bytes(32)
    code_challenge = _code_challenge(code_verifier)
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": config.mcp_url,
    }
    return RobinhoodPKCEFlow(
        authorization_url=f"{config.authorization_endpoint}?{urlencode(params)}",
        state=state,
        code_verifier=code_verifier,
        client_id=client_id,
        redirect_uri=config.redirect_uri,
        scope=config.scope,
        mcp_url=config.mcp_url,
        token_endpoint=config.token_endpoint,
    )


def register_oauth_client(config: RobinhoodOAuthConfig) -> str:
    payload = {
        "client_name": config.client_name,
        "redirect_uris": [config.redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": config.scope,
    }
    try:
        response = requests.post(
            config.registration_endpoint,
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RobinhoodMCPUnavailable(str(exc)) from exc
    if response.status_code >= 400:
        raise RobinhoodMCPAuthError(f"registration HTTP {response.status_code}: {response.text[:300]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise RobinhoodMCPBadResponse("registration response was not valid JSON") from exc
    client_id = data.get("client_id")
    if not client_id:
        raise RobinhoodMCPBadResponse("registration response did not include client_id")
    return str(client_id)


def exchange_oauth_callback(callback_url: str, flow: RobinhoodPKCEFlow) -> dict[str, Any]:
    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)
    code = (params.get("code") or [""])[0]
    state = (params.get("state") or [""])[0]
    if not code:
        raise RobinhoodMCPAuthError("OAuth callback did not include code")
    if state != flow.state:
        raise RobinhoodMCPAuthError("OAuth callback state did not match the pending login flow")
    return exchange_authorization_code(code, flow)


def exchange_authorization_code(code: str, flow: RobinhoodPKCEFlow) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": flow.client_id,
        "redirect_uri": flow.redirect_uri,
        "code_verifier": flow.code_verifier,
    }
    try:
        response = requests.post(
            flow.token_endpoint,
            data=payload,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RobinhoodMCPUnavailable(str(exc)) from exc
    if response.status_code >= 400:
        raise RobinhoodMCPAuthError(f"token HTTP {response.status_code}: {response.text[:300]}")
    try:
        token = response.json()
    except ValueError as exc:
        raise RobinhoodMCPBadResponse("token response was not valid JSON") from exc
    if not token.get("access_token"):
        raise RobinhoodMCPAuthError("token response did not include access_token")
    token.setdefault("client_id", flow.client_id)
    token.setdefault("mcp_url", flow.mcp_url)
    token.setdefault("token_endpoint", flow.token_endpoint)
    token.setdefault("obtained_at", int(time.time()))
    return token


def wait_for_oauth_callback(redirect_uri: str, *, timeout_seconds: float = 180.0) -> str:
    """Listen for a single OAuth redirect and return the full callback URL."""
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or not parsed.hostname or not parsed.port:
        raise RobinhoodMCPAuthError("local OAuth listener requires an http://host:port redirect_uri")
    expected_path = parsed.path or "/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            path = urlparse(self.path).path or "/"
            if path != expected_path:
                self.send_response(404)
                self.end_headers()
                return
            callback_url = f"{redirect_uri.split('?', 1)[0]}?{urlparse(self.path).query}"
            self.server.callback_url = callback_url  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>Robinhood MCP login complete. You can close this tab.</body></html>")

    server = HTTPServer((parsed.hostname, parsed.port), Handler)
    server.callback_url = None  # type: ignore[attr-defined]
    deadline = time.monotonic() + max(float(timeout_seconds), 1.0)
    try:
        while time.monotonic() < deadline and not server.callback_url:  # type: ignore[attr-defined]
            server.timeout = min(1.0, max(deadline - time.monotonic(), 0.0))
            server.handle_request()
    finally:
        server.server_close()
    callback_url = server.callback_url  # type: ignore[attr-defined]
    if not callback_url:
        raise RobinhoodMCPAuthError("timed out waiting for Robinhood OAuth callback")
    return str(callback_url)


def refresh_oauth_token(token: dict[str, Any], *, token_endpoint: str | None = None) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    client_id = token.get("client_id")
    if not refresh_token or not client_id:
        raise RobinhoodMCPAuthError("stored token cannot be refreshed without refresh_token and client_id")
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    endpoint = token_endpoint or token.get("token_endpoint") or DEFAULT_TOKEN_ENDPOINT
    try:
        response = requests.post(
            endpoint,
            data=payload,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RobinhoodMCPUnavailable(str(exc)) from exc
    if response.status_code >= 400:
        raise RobinhoodMCPAuthError(f"refresh HTTP {response.status_code}: {response.text[:300]}")
    try:
        refreshed = response.json()
    except ValueError as exc:
        raise RobinhoodMCPBadResponse("refresh response was not valid JSON") from exc
    if not refreshed.get("access_token"):
        raise RobinhoodMCPAuthError("refresh response did not include access_token")
    merged = {**token, **refreshed}
    if not merged.get("refresh_token"):
        merged["refresh_token"] = refresh_token
    merged["client_id"] = client_id
    merged["token_endpoint"] = endpoint
    merged["obtained_at"] = int(time.time())
    return merged


def save_json_file(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    target.chmod(0o600)
    return target


def load_json_file(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    if not target.exists():
        raise RobinhoodMCPAuthError(f"token file not found: {target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RobinhoodMCPBadResponse(f"token file was not valid JSON: {target}") from exc
    if not isinstance(data, dict):
        raise RobinhoodMCPBadResponse(f"token file root must be an object: {target}")
    return data


def token_is_expiring(token: dict[str, Any], *, skew_seconds: int = 300) -> bool:
    expires_in = _safe_int(token.get("expires_in"))
    obtained_at = _safe_int(token.get("obtained_at"))
    if expires_in is None or obtained_at is None:
        return False
    return int(time.time()) >= obtained_at + expires_in - skew_seconds


class RobinhoodMCPClient:
    def __init__(
        self,
        *,
        mcp_url: str = DEFAULT_MCP_URL,
        access_token: str | None = None,
        token_path: str | Path | None = None,
        token_endpoint: str = DEFAULT_TOKEN_ENDPOINT,
        timeout_seconds: float = 20.0,
    ):
        self.mcp_url = mcp_url
        self.access_token = access_token
        self.token_path = Path(token_path).expanduser() if token_path else None
        self.token_endpoint = token_endpoint
        self.timeout_seconds = timeout_seconds
        self.session_id: str | None = None
        self._next_id = 1
        self._token_payload: dict[str, Any] | None = None

    def initialize(self) -> dict[str, Any]:
        status, headers, data = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": self._id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "AlpacaTradingAgent", "version": "0.1.0"},
                },
            }
        )
        self.session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        if status != 200:
            raise RobinhoodMCPUnavailable(f"initialize HTTP {status}: {data}")
        self._post_json({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return data

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.session_id:
            self.initialize()
        _, _, data = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": self._id(),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments or {}},
            }
        )
        if not isinstance(data, dict):
            raise RobinhoodMCPBadResponse("MCP tool response root must be an object")
        if data.get("error"):
            raise RobinhoodMCPUnavailable(str(data["error"]))
        return data

    def list_tools(self) -> list[dict[str, Any]]:
        if not self.session_id:
            self.initialize()
        _, _, data = self._post_json({"jsonrpc": "2.0", "id": self._id(), "method": "tools/list", "params": {}})
        result = data.get("result") if isinstance(data, dict) else None
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise RobinhoodMCPBadResponse("tools/list response did not include a tools array")
        return tools

    def get_equity_quote(self, symbol: str) -> dict[str, Any]:
        data = self._tool_payload("get_equity_quotes", {"symbols": [symbol.upper()]})
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            raise RobinhoodMCPBadResponse(f"quote response did not include results for {symbol}")
        return results[0]

    def get_accounts(self) -> list[dict[str, Any]]:
        data = self._tool_payload("get_accounts", {})
        accounts = data.get("accounts") if isinstance(data, dict) else None
        return accounts if isinstance(accounts, list) else []

    def get_portfolio(self, account_number: str) -> dict[str, Any]:
        data = self._tool_payload("get_portfolio", {"account_number": account_number})
        if not isinstance(data, dict):
            raise RobinhoodMCPBadResponse("portfolio response did not include object data")
        return data

    def get_equity_positions(self, account_number: str) -> list[dict[str, Any]]:
        data = self._tool_payload("get_equity_positions", {"account_number": account_number})
        if isinstance(data, dict):
            for key in ("positions", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def review_equity_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        data = self._tool_payload("review_equity_order", arguments)
        if not isinstance(data, dict):
            raise RobinhoodMCPBadResponse("review_equity_order response did not include object data")
        return data

    def place_equity_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        data = self._tool_payload("place_equity_order", arguments)
        if not isinstance(data, dict):
            raise RobinhoodMCPBadResponse("place_equity_order response did not include object data")
        return data

    def _tool_payload(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        response = self.call_tool(tool_name, arguments)
        result = response.get("result")
        if not isinstance(result, dict):
            raise RobinhoodMCPBadResponse(f"{tool_name} response missing result object")
        if result.get("isError"):
            raise RobinhoodMCPUnavailable(_extract_mcp_text(result) or f"{tool_name} returned MCP error")
        if isinstance(result.get("structuredContent"), (dict, list)):
            structured = result["structuredContent"]
            if isinstance(structured, dict) and "data" in structured:
                return structured["data"]
            return structured
        text = _extract_mcp_text(result)
        if text:
            try:
                decoded = json.loads(text)
            except ValueError:
                return {"text": text}
            if isinstance(decoded, dict) and "data" in decoded:
                return decoded["data"]
            return decoded
        return result

    def _post_json(self, payload: dict[str, Any]) -> tuple[int, dict[str, str], dict[str, Any]]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token()}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            response = requests.post(self.mcp_url, json=payload, headers=headers, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RobinhoodMCPUnavailable(str(exc)) from exc
        if response.status_code == 401 and self._refresh_stored_token():
            headers["Authorization"] = f"Bearer {self._access_token()}"
            response = requests.post(self.mcp_url, json=payload, headers=headers, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise RobinhoodMCPUnavailable(f"MCP HTTP {response.status_code}: {response.text[:300]}")
        if not response.text.strip():
            return response.status_code, dict(response.headers), {}
        try:
            data = decode_mcp_response(response)
        except Exception as exc:
            raise RobinhoodMCPBadResponse(f"MCP response was not readable: {response.text[:300]}") from exc
        return response.status_code, dict(response.headers), data

    def _access_token(self) -> str:
        if self.access_token:
            return self.access_token
        if self.token_path is None:
            raise RobinhoodMCPAuthError("Robinhood access token or token_path is required")
        if self._token_payload is None:
            self._token_payload = load_json_file(self.token_path)
        if token_is_expiring(self._token_payload):
            self._refresh_stored_token()
        token = self._token_payload.get("access_token") if self._token_payload else None
        if not token:
            raise RobinhoodMCPAuthError("stored token file did not include access_token")
        return str(token)

    def _refresh_stored_token(self) -> bool:
        if self.token_path is None:
            return False
        token = self._token_payload or load_json_file(self.token_path)
        if not token.get("refresh_token"):
            return False
        refreshed = refresh_oauth_token(token, token_endpoint=self.token_endpoint)
        save_json_file(self.token_path, refreshed)
        self._token_payload = refreshed
        self.access_token = None
        return True

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value


def open_authorization_url(url: str) -> None:
    webbrowser.open(url)


def summarize_token(token: dict[str, Any]) -> dict[str, Any]:
    return {
        "token_type": token.get("token_type"),
        "expires_in": token.get("expires_in"),
        "scope": token.get("scope"),
        "has_access_token": bool(token.get("access_token")),
        "has_refresh_token": bool(token.get("refresh_token")),
        "has_user_uuid": bool(token.get("user_uuid")),
        "client_id": token.get("client_id"),
    }


def mask_account_number(value: str) -> str:
    text = str(value or "")
    if len(text) <= 4:
        return "****"
    return "****" + text[-4:]


def _extract_mcp_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n\n".join(part for part in parts if part.strip())


def _token_urlsafe_bytes(size: int) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(size)).rstrip(b"=").decode("ascii")


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None

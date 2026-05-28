from __future__ import annotations

import json

import pandas as pd
from pydantic import ValidationError

from tradingagents.dataflows.ta_schema import Direction, TechnicalBrief
from tradingagents.dataflows.technical_brief import build_technical_brief


def _mock_ohlcv(days: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = pd.Series(range(days), dtype=float) * 0.1 + 100
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000,
        }
    )


def test_technical_brief_schema_validates_mocked_ohlcv(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.technical_brief.AlpacaUtils.get_stock_data",
        lambda **_kwargs: _mock_ohlcv(),
    )

    brief = build_technical_brief("AAPL", "2026-01-02")
    payload = json.loads(brief.model_dump_json())

    assert payload["symbol"] == "AAPL"
    assert {item["timeframe"] for item in payload["timeframes"]} == {"1h", "4h", "1d"}
    assert payload["signal_summary"]["confidence"] in {"high", "medium", "low"}
    assert "last_close" in payload["raw_prices"]
    assert "risk_overlays" in payload
    assert "price_vs_50d" in payload["risk_overlays"]


def test_schema_rejects_invalid_direction_contract():
    valid_payload = {
        "symbol": "AAPL",
        "generated_at": "2026-01-02T00:00:00Z",
        "timeframes": [],
        "key_levels": [],
        "signal_summary": {
            "setup": "none",
            "confidence": "low",
            "description": "No setup.",
        },
        "raw_prices": {"last_close": 100.0},
    }

    brief = TechnicalBrief.model_validate(valid_payload)
    assert brief.signal_summary.confidence == "low"
    assert Direction.BULLISH.value == "bullish"

    invalid_payload = dict(valid_payload)
    invalid_payload["signal_summary"] = dict(valid_payload["signal_summary"], confidence="certain")
    try:
        TechnicalBrief.model_validate(invalid_payload)
    except ValidationError as exc:
        assert "confidence" in str(exc)
    else:
        raise AssertionError("invalid schema payload should fail validation")

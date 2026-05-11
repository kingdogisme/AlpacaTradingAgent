import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingagents.agents.utils.agent_trading_modes import get_horizon_context
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.technical_brief import build_trend_brief
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.signal_processing import SignalProcessor
from webui.utils.storage import DEFAULT_SETTINGS


class FailingLLM:
    def invoke(self, _messages):
        raise AssertionError("deterministic parser should handle final proposals")


def _mock_ohlcv(days=1800):
    dates = pd.date_range("2021-01-01", periods=days, freq="B")
    close = pd.Series(range(days), dtype=float) * 0.05 + 100
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


class TradingHorizonTests(unittest.TestCase):
    def test_default_and_profiles_are_stable(self):
        self.assertEqual(DEFAULT_CONFIG["trading_horizon"], "swing")
        self.assertFalse(DEFAULT_CONFIG["trend_execution_enabled"])

        expected = {
            "swing": ("Swing", "2-10 trading days", "1h/4h/1d"),
            "position": ("Position", "1-3 months", "1d/1w"),
            "trend": ("Trend", "3-6 months", "1w/1mo"),
        }
        for horizon, (label, holding, timeframes) in expected.items():
            with self.subTest(horizon=horizon):
                context = get_horizon_context({"trading_horizon": horizon})
                self.assertEqual(context["horizon"], horizon)
                self.assertEqual(context["label"], label)
                self.assertEqual(context["holding_period"], holding)
                self.assertEqual(context["primary_timeframes"], timeframes)

        self.assertEqual(get_horizon_context({})["horizon"], "swing")

    def test_webui_storage_defaults_include_swing_horizon(self):
        self.assertEqual(DEFAULT_SETTINGS["trading_horizon"], "swing")
        self.assertFalse(DEFAULT_SETTINGS["trend_execution_enabled"])

    def test_trend_brief_schema_validates_with_mocked_ohlcv(self):
        data = _mock_ohlcv()

        with patch(
            "tradingagents.dataflows.technical_brief.AlpacaUtils.get_stock_data",
            return_value=data,
        ):
            brief = build_trend_brief("AAPL", "2026-01-02", "trend")

        payload = json.loads(brief.model_dump_json())
        self.assertEqual(payload["horizon"], "trend")
        self.assertEqual(payload["holding_period"], "3-6 months")
        self.assertTrue(payload["timeframes"])
        self.assertIn("relative_strength", payload)
        self.assertIn("invalidation", payload)
        self.assertIn("regime_alignment", payload)

    def test_memory_prioritizes_same_ticker_same_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            log = TradingMemoryLog({"memory_log_path": str(path)})
            final = "Decision.\nFINAL TRANSACTION PROPOSAL: **BUY**"

            log.store_decision("AAPL", "2026-01-02", final, horizon="trend")
            log.store_decision("AAPL", "2026-01-03", final, horizon="swing")
            log.update_with_outcome("AAPL", "2026-01-02", 0.05, None, 126, "Trend lesson.")
            log.update_with_outcome("AAPL", "2026-01-03", 0.01, None, 5, "Swing lesson.")

            context = log.get_past_context("AAPL", horizon="trend")
            self.assertLess(context.find("Past trend analyses"), context.find("Other-horizon"))
            self.assertIn("Trend lesson.", context)
            self.assertIn("Swing lesson.", context)

    def test_signal_parser_accepts_trend_mode_actions(self):
        processor = SignalProcessor(FailingLLM())
        self.assertEqual(
            processor.process_signal("Thesis.\nFINAL TRANSACTION PROPOSAL: **HOLD**"),
            "HOLD",
        )
        self.assertEqual(
            processor.process_signal("Thesis.\nFINAL TRANSACTION PROPOSAL: **LONG**"),
            "LONG",
        )
        self.assertEqual(
            processor.process_signal("Thesis.\nFINAL TRANSACTION PROPOSAL: **NEUTRAL**"),
            "NEUTRAL",
        )

    def test_prompt_rendering_keeps_swing_language_only_in_swing_horizon(self):
        swing_context = get_horizon_context({"trading_horizon": "swing"})
        position_context = get_horizon_context({"trading_horizon": "position"})
        trend_context = get_horizon_context({"trading_horizon": "trend"})

        self.assertIn("2-10 trading day decisions", swing_context["instructions"])
        self.assertNotIn("2-10 trading days", position_context["instructions"])
        self.assertNotIn("2-10 trading days", trend_context["instructions"])


if __name__ == "__main__":
    unittest.main()

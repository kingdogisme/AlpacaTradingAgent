import tempfile
import unittest
from pathlib import Path

from tradingagents.agents.utils.memory import TradingMemoryLog


FINAL_BUY = """Thesis body.

**Advisory Rating**: Overweight

FINAL TRANSACTION PROPOSAL: **BUY**"""


class TradingMemoryLogTests(unittest.TestCase):
    def test_store_dedupe_and_resolve_equity_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            log = TradingMemoryLog({"memory_log_path": str(path), "memory_log_max_entries": 3})

            log.store_decision("AAPL", "2026-01-02", FINAL_BUY)
            log.store_decision("AAPL", "2026-01-02", FINAL_BUY)

            entries = log.load_entries()
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0]["pending"])
            self.assertEqual(entries[0]["action"], "BUY")
            self.assertEqual(entries[0]["rating"], "Overweight")
            self.assertEqual(entries[0]["horizon"], "swing")

            log.update_with_outcome(
                ticker="AAPL",
                trade_date="2026-01-02",
                raw_return=0.04,
                alpha_return=0.01,
                holding_days=5,
                reflection="The setup worked.",
            )

            entries = log.load_entries()
            self.assertFalse(entries[0]["pending"])
            self.assertEqual(entries[0]["raw"], "+4.0%")
            self.assertEqual(entries[0]["alpha"], "+1.0%")
            self.assertIn("The setup worked.", log.get_past_context("AAPL"))

    def test_rotation_keeps_pending_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            log = TradingMemoryLog({"memory_log_path": str(path), "memory_log_max_entries": 1})

            log.store_decision("AAPL", "2026-01-01", FINAL_BUY)
            log.store_decision("MSFT", "2026-01-02", FINAL_BUY)
            log.update_with_outcome("AAPL", "2026-01-01", 0.02, None, 5, "First resolved.")

            entries = log.load_entries()
            self.assertEqual(len(entries), 2)
            self.assertEqual(len([entry for entry in entries if entry["pending"]]), 1)

    def test_same_ticker_and_date_resolve_independently_by_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            log = TradingMemoryLog({"memory_log_path": str(path)})

            for horizon in ("swing", "position", "trend"):
                log.store_decision("AAPL", "2026-01-02", FINAL_BUY, horizon=horizon)

            log.batch_update_with_outcomes(
                [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-01-02",
                        "horizon": "swing",
                        "raw_return": 0.01,
                        "alpha_return": None,
                        "holding_days": 5,
                        "reflection": "Swing resolved.",
                    },
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-01-02",
                        "horizon": "position",
                        "raw_return": 0.05,
                        "alpha_return": 0.02,
                        "holding_days": 63,
                        "reflection": "Position resolved.",
                    },
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-01-02",
                        "horizon": "trend",
                        "raw_return": 0.08,
                        "alpha_return": 0.03,
                        "holding_days": 126,
                        "reflection": "Trend resolved.",
                    },
                ]
            )

            entries = sorted(log.load_entries(), key=lambda entry: entry["horizon"])
            self.assertEqual([entry["horizon"] for entry in entries], ["position", "swing", "trend"])
            self.assertEqual(entries[0]["holding"], "63d")
            self.assertEqual(entries[1]["holding"], "5d")
            self.assertEqual(entries[2]["holding"], "126d")
            self.assertIn("Trend resolved.", log.get_past_context("AAPL", horizon="trend"))

    def test_legacy_entries_without_horizon_parse_and_resolve_as_swing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            path.write_text(
                "[2026-01-02 | AAPL | BUY | Overweight | pending]\n\n"
                "DECISION:\nLegacy decision body.\n\n<!-- ENTRY_END -->\n\n",
                encoding="utf-8",
            )
            log = TradingMemoryLog({"memory_log_path": str(path)})

            entries = log.load_entries()
            self.assertEqual(entries[0]["horizon"], "swing")
            self.assertTrue(entries[0]["pending"])

            log.update_with_outcome(
                ticker="AAPL",
                trade_date="2026-01-02",
                raw_return=0.03,
                alpha_return=None,
                holding_days=5,
                reflection="Legacy resolved.",
            )

            entries = log.load_entries()
            self.assertFalse(entries[0]["pending"])
            self.assertEqual(entries[0]["horizon"], "swing")
            self.assertIn("Legacy resolved.", entries[0]["reflection"])


if __name__ == "__main__":
    unittest.main()

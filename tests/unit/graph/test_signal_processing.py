import unittest

from tradingagents.graph.signal_processing import SignalProcessor


class FailingLLM:
    def invoke(self, _messages):
        raise AssertionError("LLM should not be called for deterministic final proposals")


class SignalProcessorTests(unittest.TestCase):
    def test_extracts_executable_action_without_llm(self):
        processor = SignalProcessor(FailingLLM())

        self.assertEqual(
            processor.process_signal("Advisory Rating: Overweight\nFINAL TRANSACTION PROPOSAL: **BUY**"),
            "BUY",
        )
        self.assertEqual(
            processor.process_signal("FINAL TRANSACTION PROPOSAL: **SHORT**"),
            "SHORT",
        )
        self.assertEqual(
            processor.process_signal("Quarterly thesis intact.\nFINAL TRANSACTION PROPOSAL: **NEUTRAL**"),
            "NEUTRAL",
        )
        self.assertEqual(
            processor.process_signal("Trend thesis still valid.\nFINAL TRANSACTION PROPOSAL: **HOLD**"),
            "HOLD",
        )


if __name__ == "__main__":
    unittest.main()

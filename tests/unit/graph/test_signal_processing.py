import unittest

from tradingagents.graph.signal_processing import SignalProcessor


class FailingLLM:
    def invoke(self, _messages):
        raise AssertionError("LLM should not be called for deterministic final proposals")


class SignalProcessorTests(unittest.TestCase):
    def test_extracts_executable_action_without_llm(self):
        processor = SignalProcessor(FailingLLM())

        self.assertEqual(
            processor.process_signal("Advisory Rating: STRONG BUY\nFINAL TRANSACTION PROPOSAL: **BUY**"),
            "BUY",
        )
        self.assertEqual(
            processor.process_signal("Advisory Rating: STRONG SELL\nFINAL TRANSACTION PROPOSAL: **HOLD**"),
            "HOLD",
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

    def test_advisory_rating_tail_does_not_short_circuit_to_action(self):
        class EchoLLM:
            def invoke(self, _messages):
                return type("Message", (), {"content": "NEUTRAL"})()

        processor = SignalProcessor(EchoLLM())

        self.assertEqual(
            processor.process_signal("Risk controls support staying flat.\n**Advisory Rating**: **STRONG SELL**"),
            "NEUTRAL",
        )


if __name__ == "__main__":
    unittest.main()

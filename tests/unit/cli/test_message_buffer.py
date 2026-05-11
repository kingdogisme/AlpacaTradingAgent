from __future__ import annotations

from cli.main import MessageBuffer


def test_message_buffer_updates_status_and_report_sections():
    buffer = MessageBuffer(max_length=2)

    buffer.add_message("info", "first")
    buffer.add_message("info", "second")
    buffer.add_message("info", "third")
    buffer.update_agent_status("Market Analyst", "completed")
    buffer.update_report_section("market_report", "Market body.")
    buffer.update_report_section("final_trade_decision", "FINAL TRANSACTION PROPOSAL: **BUY**")

    assert len(buffer.messages) == 2
    assert buffer.current_agent == "Market Analyst"
    assert buffer.agent_status["Market Analyst"] == "completed"
    assert "Portfolio Management Decision" in buffer.final_report
    assert "FINAL TRANSACTION PROPOSAL: **BUY**" in buffer.final_report


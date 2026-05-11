from __future__ import annotations

from tradingagents.agents.utils.agent_trading_modes import (
    ensure_final_transaction_proposal,
    extract_recommendation,
    get_position_transition,
    get_trading_mode_context,
    validate_recommendation,
)


def test_advisory_rating_does_not_override_executable_action():
    content = """
**Advisory Rating**: Sell

Risk controls support a smaller entry.

FINAL TRANSACTION PROPOSAL: **BUY**
"""

    assert extract_recommendation(content, "investment") == "BUY"


def test_ensure_final_transaction_proposal_preserves_existing_analysis():
    result = ensure_final_transaction_proposal(
        "Risk analysis body.",
        "NEUTRAL",
        "trading",
    )

    assert result.startswith("Risk analysis body.")
    assert result.endswith("FINAL TRANSACTION PROPOSAL: **NEUTRAL**")


def test_trading_mode_context_and_validation_are_mode_specific():
    investment = get_trading_mode_context({"allow_shorts": False})
    trading = get_trading_mode_context({"allow_shorts": True}, current_position="LONG")

    assert investment["action_list"] == ["BUY", "HOLD", "SELL"]
    assert trading["action_list"] == ["LONG", "NEUTRAL", "SHORT"]
    assert validate_recommendation("SELL", "investment")
    assert not validate_recommendation("SELL", "trading")


def test_position_transition_contract_covers_reversal_and_neutral_paths():
    assert get_position_transition("LONG", "SHORT")["action"] == "REVERSE_TO_SHORT"
    assert get_position_transition("SHORT", "LONG")["action"] == "REVERSE_TO_LONG"
    assert get_position_transition("NEUTRAL", "NEUTRAL")["action"] == "STAY_NEUTRAL"


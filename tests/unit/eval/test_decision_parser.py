from tradingagents.eval.decision_parser import parse_decision_text


def test_parse_investment_final_decision_fields():
    decision = parse_decision_text(
        """**Action**: BUY
**Confidence**: high
**Advisory Rating**: Overweight
**Thesis**: Upside is supported.
**Invalidation**: Break below support.
**Position Plan**: Build on confirmation.
**Risk Budget**: 1% portfolio risk.

FINAL TRANSACTION PROPOSAL: **BUY**""",
        run_id="run-1",
        stage="final",
        agent_name="Risk Manager",
        trading_mode="investment",
        horizon="swing",
    )

    assert decision.action == "BUY"
    assert decision.confidence == "high"
    assert decision.advisory_rating == "Overweight"
    assert decision.thesis == "Upside is supported."
    assert decision.invalidation == "Break below support."
    assert decision.position_plan == "Build on confirmation."
    assert decision.risk_budget == "1% portfolio risk."
    assert decision.parser_status == "ok"


def test_parse_trading_mode_action_without_explicit_mode():
    decision = parse_decision_text(
        "Reasoning.\n**Confidence**: medium\nFINAL TRANSACTION PROPOSAL: **SHORT**",
        run_id="run-2",
        stage="trader",
        agent_name="Trader",
    )

    assert decision.action == "SHORT"
    assert decision.trading_mode == "trading"
    assert decision.confidence == "medium"


def test_parse_missing_action_is_partial():
    decision = parse_decision_text(
        "No executable line.\n**Confidence**: low",
        run_id="run-3",
        stage="final",
        agent_name="Risk Manager",
    )

    assert decision.action is None
    assert decision.parser_status == "partial"
    assert "action_not_found" in decision.parser_warnings

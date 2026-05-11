from __future__ import annotations

from tradingagents.agents.utils.report_context import (
    build_debate_digest,
    build_report_context_index,
    get_agent_context_bundle,
)


def _state_with_reports() -> dict:
    return {
        "company_of_interest": "AAPL",
        "macro_report": "## Rates\n- CPI risk remains high at 3.2% with yield pressure.",
        "market_report": "## Trend\n- Price is above 50D SMA with RSI 61 and support at $190.",
        "sentiment_report": "## Social\n- Sentiment is bullish but crowded into earnings.",
        "news_report": "## News\n- Product launch and analyst upgrade support momentum.",
        "fundamentals_report": "## Fundamentals\n- Revenue growth improved and margin risk remains limited.",
    }


def test_report_context_index_keeps_all_analyst_reports_represented():
    context = build_report_context_index(_state_with_reports())

    assert context["stats"]["reports_with_content"] == 5
    assert set(context["reports"]) == {
        "macro_report",
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
    }
    assert context["chunks"]
    assert "Market" in context["global_overview"]


def test_agent_context_bundle_includes_claim_matrix_and_selected_chunks():
    state = _state_with_reports()
    bundle = get_agent_context_bundle(
        state,
        agent_role="trader",
        objective="Create a risk-aware plan using technical support and earnings catalysts.",
    )

    assert "Decision Claim Matrix" in bundle["decision_claim_matrix"]
    assert "Cross-Analyst Context Packet" in bundle["analysis_context"]
    assert bundle["selected_chunk_ids"]
    assert state["report_context"]["stats"]["reports_with_content"] == 5


def test_debate_digest_compacts_investment_and_risk_state():
    investment_digest = build_debate_digest(
        {
            "count": 2,
            "current_response": "Bull Analyst: Momentum is improving.",
            "bull_messages": ["Bull Analyst: Support held at 190."],
            "bear_messages": ["Bear Analyst: Valuation is stretched."],
        },
        "investment",
    )
    risk_digest = build_debate_digest(
        {
            "count": 3,
            "latest_speaker": "Neutral",
            "current_risky_response": "Risky Analyst: Let winners run.",
            "current_safe_response": "Safe Analyst: Size down.",
            "current_neutral_response": "Neutral Analyst: Wait for confirmation.",
        },
        "risk",
    )

    assert "Investment Debate Digest" in investment_digest
    assert "Bull:" in investment_digest
    assert "Risk Debate Digest" in risk_digest
    assert "Latest speaker: Neutral" in risk_digest


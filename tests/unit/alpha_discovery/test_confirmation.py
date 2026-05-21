from __future__ import annotations

import pandas as pd

from tradingagents.alpha_discovery.confirmation import ConfirmationConfig, apply_confirmations
from tradingagents.alpha_discovery.market_data import price_volume_confirmation_from_bars
from tradingagents.alpha_discovery.models import OpportunityCandidate, SourceSignal


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses.get(name, "No articles found")


class FakeFundamentalProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def sec_fundamental_confirmation(self, ticker):
        self.calls.append(ticker)
        return self.response


def test_social_only_high_heat_remains_b_without_confirmation():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MU",
        tier="B",
        alpha_score=0.78,
        opportunity_type="continuation",
        direction_hint="bullish",
        theme="Memory/Semiconductor",
        catalyst="WSB high heat theme: memory pricing catalyst",
        score_components={"social_heat": 0.65},
    )
    client = FakeClient({"get_stock_news": "No articles found"})

    apply_confirmations([candidate], client=client, config=ConfirmationConfig(news_enabled=True, options_enabled=False))

    assert candidate.tier == "B"
    assert candidate.score_components["confirmation_sources"] == []


def test_independent_news_confirmation_promotes_high_score_to_a():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MU",
        tier="B",
        alpha_score=0.78,
        opportunity_type="continuation",
        direction_hint="bullish",
        theme="Memory/Semiconductor",
        catalyst="WSB high heat theme: memory pricing catalyst",
        discovered_at="2026-05-20T13:00:00+00:00",
        score_components={"social_heat": 0.65},
    )
    client = FakeClient(
        {
            "get_stock_news": "Total articles: 3\n- 2026-05-20 MU memory pricing confirms company catalyst. " * 8,
        }
    )

    apply_confirmations([candidate], client=client, config=ConfirmationConfig(news_enabled=True, options_enabled=False))

    assert candidate.tier == "A"
    assert candidate.alpha_score == 0.94
    assert candidate.score_components["confirmation_sources"] == ["direct_news"]
    assert candidate.source_signals[0].source == "sellthenews_stock_news_confirmation"


def test_options_confirmation_adds_component_without_news():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="NVDA",
        tier="B",
        alpha_score=0.75,
        opportunity_type="volatility",
        direction_hint="mixed",
    )
    client = FakeClient(
        {
            "get_options_data": (
                "Gamma Flip: 100\nNet GEX: 123456\nCall wall: 110\nPut wall: 90\n"
                "Options exposure data " * 20
            ),
        }
    )

    apply_confirmations([candidate], client=client, config=ConfirmationConfig(news_enabled=False, options_enabled=True))

    assert "options" in candidate.score_components["confirmation_sources"]
    assert candidate.score_components["options_pressure"] == 0.12


def test_search_and_live_news_can_confirm_when_context_matches():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="RKLB",
        tier="B",
        alpha_score=0.74,
        opportunity_type="continuation",
        direction_hint="bullish",
        theme="space launch contracts",
        catalyst="RKLB launch contract catalyst",
        discovered_at="2026-05-20T13:00:00+00:00",
        score_components={"social_heat": 0.6},
    )
    client = FakeClient(
        {
            "search_news": "Total articles: 2\n- 2026-05-20 RKLB wins new launch contract and space order. " * 8,
            "get_live_news": "Total articles: 2\n- 2026-05-20 RKLB launch contract revenue catalyst. " * 8,
        }
    )

    apply_confirmations(
        [candidate],
        client=client,
        config=ConfirmationConfig(news_enabled=False, search_news_enabled=True, live_news_enabled=True, options_enabled=False),
    )

    assert candidate.tier == "A"
    assert candidate.score_components["confirmation_sources"] == ["live_news", "search_news"]
    assert candidate.score_components["news_confirmation"] > 0.18


def test_generic_stock_news_does_not_confirm_without_theme_overlap():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MU",
        tier="B",
        alpha_score=0.78,
        opportunity_type="continuation",
        direction_hint="bullish",
        theme="Memory/Semiconductor",
        catalyst="WSB high heat theme: DRAM shortage and memory pricing",
        score_components={"social_heat": 0.65},
    )
    client = FakeClient(
        {
            "get_stock_news": "Total articles: 5\n- MU board member attends broad technology conference. " * 10,
        }
    )

    apply_confirmations([candidate], client=client, config=ConfirmationConfig(news_enabled=True, options_enabled=False))

    assert candidate.tier == "B"
    assert candidate.score_components["confirmation_sources"] == []


def test_bearish_continuation_is_blocked_from_a_even_with_confirmation():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MSFT",
        tier="B",
        alpha_score=0.78,
        opportunity_type="continuation",
        direction_hint="bearish",
        theme="AI capex pressure",
        catalyst="WSB high heat theme: AI capex margin pressure",
        discovered_at="2026-05-20T13:00:00+00:00",
        score_components={"social_heat": 0.65},
    )
    client = FakeClient(
        {
            "get_stock_news": "Total articles: 3\n- 2026-05-20 MSFT AI capex spending pressures margins and guidance. " * 8,
        }
    )

    apply_confirmations([candidate], client=client, config=ConfirmationConfig(news_enabled=True, options_enabled=False))

    assert candidate.tier == "B"
    assert candidate.score_components["promotion_gate"] == "blocked_direction_conflict"
    assert "direction_conflict" in candidate.risk_flags


def test_price_volume_confirmation_can_promote_candidate():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MU",
        tier="B",
        alpha_score=0.72,
        opportunity_type="continuation",
        direction_hint="bullish",
        score_components={"social_heat": 0.65},
    )

    class Provider:
        def price_volume_confirmation(self, ticker):
            return {
                "confirmed": True,
                "relative_volume": 2.2,
                "one_day_move": 0.04,
                "five_day_move": 0.08,
                "confirmation_strength": 0.18,
            }

    apply_confirmations(
        [candidate],
        client=FakeClient({}),
        market_data_provider=Provider(),
        config=ConfirmationConfig(news_enabled=False, options_enabled=False, price_volume_enabled=True),
    )

    assert candidate.tier == "A"
    assert candidate.alpha_score == 0.9
    assert candidate.score_components["confirmation_sources"] == ["price_volume"]


def test_price_volume_helper_flags_overextended_moves_as_unconfirmed():
    bars = pd.DataFrame(
        {
            "open": [10, 10.5, 11, 12, 14, 15],
            "close": [10.2, 10.6, 11.5, 13.5, 15.2, 18.5],
            "volume": [100, 100, 110, 120, 130, 500],
        }
    )

    result = price_volume_confirmation_from_bars("MU", bars, max_abs_5d_move=0.25)

    assert result["confirmed"] is False
    assert result["overextended"] is True


def test_price_volume_helper_rejects_stale_bars():
    bars = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01", periods=6, freq="D"),
            "open": [10, 10.5, 11, 12, 12.5, 13],
            "close": [10.2, 10.6, 11.5, 12.8, 13.1, 13.7],
            "volume": [100, 100, 110, 120, 130, 500],
        }
    )

    result = price_volume_confirmation_from_bars("MU", bars, as_of="2026-05-20", max_bar_age_days=5)

    assert result["confirmed"] is False
    assert result["reason"] == "stale price/volume bars"
    assert result["latest_bar_date"] == "2026-04-06"


def test_dd_requires_two_confirmations_for_a_by_default():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MNDY",
        tier="B",
        alpha_score=0.74,
        opportunity_type="volatility",
        direction_hint="bullish",
        theme="WSB DD",
        catalyst="earnings options catalyst",
        discovered_at="2026-05-20T13:00:00+00:00",
        score_components={"dd_quality": 0.74},
        source_signals=[SourceSignal("c1", "sellthenews_wsb_dd", "mcp://sellthenews/dd/1")],
    )
    client = FakeClient(
        {
            "get_stock_news": "Total articles: 3\n- 2026-05-20 MNDY earnings revenue catalyst confirms options setup. " * 8,
        }
    )

    apply_confirmations([candidate], client=client, config=ConfirmationConfig(news_enabled=True, options_enabled=False))

    assert candidate.tier == "B"
    assert candidate.alpha_score == 0.9
    assert candidate.score_components["promotion_gate"] == "blocked_missing_dd_confirmations"


def test_dd_fact_check_risk_blocks_a_even_with_multiple_confirmations():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MNDY",
        tier="B",
        alpha_score=0.74,
        opportunity_type="volatility",
        direction_hint="bullish",
        theme="WSB DD",
        catalyst="earnings options catalyst",
        discovered_at="2026-05-20T13:00:00+00:00",
        risk_flags=["fact_check_risk"],
        score_components={"dd_quality": 0.74},
        source_signals=[
            SourceSignal(
                "c1",
                "sellthenews_wsb_dd",
                "mcp://sellthenews/dd/1",
                evidence_json={"fact_check_status_counts": {"questionable": 1}},
            )
        ],
    )
    client = FakeClient(
        {
            "get_stock_news": "Total articles: 3\n- 2026-05-20 MNDY earnings revenue catalyst confirms options setup. " * 8,
            "search_news": "Total articles: 3\n- 2026-05-20 MNDY earnings revenue catalyst. " * 8,
        }
    )

    apply_confirmations(
        [candidate],
        client=client,
        config=ConfirmationConfig(news_enabled=True, search_news_enabled=True, options_enabled=False),
    )

    assert candidate.tier == "B"
    assert candidate.score_components["promotion_gate"] == "blocked_dd_fact_check_risk"


def test_stale_or_undated_news_does_not_confirm_candidate():
    stale = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="MU",
        tier="B",
        alpha_score=0.78,
        opportunity_type="continuation",
        direction_hint="bullish",
        theme="Memory/Semiconductor",
        catalyst="memory pricing catalyst",
        discovered_at="2026-05-20T13:00:00+00:00",
        score_components={"social_heat": 0.65},
    )
    undated = OpportunityCandidate(
        candidate_id="c2",
        batch_id="b1",
        ticker="MU",
        tier="B",
        alpha_score=0.78,
        opportunity_type="continuation",
        direction_hint="bullish",
        theme="Memory/Semiconductor",
        catalyst="memory pricing catalyst",
        discovered_at="2026-05-20T13:00:00+00:00",
        score_components={"social_heat": 0.65},
    )

    apply_confirmations(
        [stale],
        client=FakeClient({"get_stock_news": "2026-04-01 MU memory pricing confirms company catalyst. " * 8}),
        config=ConfirmationConfig(news_enabled=True, options_enabled=False, news_max_age_days=14),
    )
    apply_confirmations(
        [undated],
        client=FakeClient({"get_stock_news": "MU memory pricing confirms company catalyst. " * 8}),
        config=ConfirmationConfig(news_enabled=True, options_enabled=False, news_max_age_days=14),
    )

    assert stale.score_components["confirmation_sources"] == []
    assert undated.score_components["confirmation_sources"] == []


def test_sec_fundamental_confirmation_adds_signal_and_component():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="NOW",
        tier="B",
        alpha_score=0.7,
        opportunity_type="continuation",
        direction_hint="bullish",
        score_components={"social_heat": 0.55},
    )
    provider = FakeFundamentalProvider(
        {
            "confirmed": True,
            "strength": 0.06,
            "flags": ["recent_filing_available", "revenue_acceleration"],
            "risk_flags": [],
            "cik": "0001373715",
            "summary": "latest_periodic=10-Q filed=2026-04-30",
        }
    )

    apply_confirmations(
        [candidate],
        client=FakeClient({}),
        fundamental_data_provider=provider,
        config=ConfirmationConfig(news_enabled=False, options_enabled=False, sec_fundamental_enabled=True),
    )

    assert provider.calls == ["NOW"]
    assert candidate.score_components["fundamental_confirmation"] == 0.06
    assert candidate.score_components["confirmation_sources"] == ["sec_filing"]
    assert candidate.source_signals[-1].source == "sec_edgar_fundamental_confirmation"
    assert candidate.source_signals[-1].evidence_json["cik"] == "0001373715"


def test_sec_confirmation_alone_does_not_promote_social_candidate_to_a():
    candidate = OpportunityCandidate(
        candidate_id="c1",
        batch_id="b1",
        ticker="NOW",
        tier="B",
        alpha_score=0.8,
        opportunity_type="continuation",
        direction_hint="bullish",
        score_components={"social_heat": 0.78},
    )
    provider = FakeFundamentalProvider(
        {
            "confirmed": True,
            "strength": 0.06,
            "flags": ["recent_filing_available"],
            "risk_flags": [],
            "summary": "recent filing exists",
        }
    )

    apply_confirmations(
        [candidate],
        client=FakeClient({}),
        fundamental_data_provider=provider,
        config=ConfirmationConfig(news_enabled=False, options_enabled=False, sec_fundamental_enabled=True),
    )

    assert candidate.alpha_score == 0.86
    assert candidate.tier == "B"
    assert candidate.score_components["confirmation_sources"] == ["sec_filing"]
    assert candidate.score_components["promotion_gate"] == "not_a_candidate"

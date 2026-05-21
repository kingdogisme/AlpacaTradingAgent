from __future__ import annotations

from tradingagents.alpha_discovery.sellthenews_dd import collect_sellthenews_dd_candidates


class FakeSellTheNewsClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        key = (name, arguments.get("postId")) if name == "get_dd_post" else name
        return self.responses[key]


DD_LIST = """=== WSB DD Posts ===
Showing 3 posts (offset: 0, more available: false)

[1good] Good SKM thesis
  Reddit title: DD: SKM Anthropic stake
  Tickers: SKM(bullish)
  score=42 | comments=25 | 2026-05-13 10:00:00 ET
---
[1bad] Bad XYZ thesis
  Reddit title: DD: XYZ too good
  Tickers: XYZ(bullish)
  score=10 | comments=10 | 2026-05-13 11:00:00 ET
---
[1more] Another SKM thesis
  Reddit title: DD: SKM second look
  Tickers: SKM(neutral)
  score=50 | comments=30 | 2026-05-13 12:00:00 ET
---"""


GOOD_POST = """=== DD Post: Good SKM thesis ===
Reddit title: DD: SKM Anthropic stake
postId: 1good | author: u/test | score: 42 | comments: 25
Analysis updated: 2026-05-13 10:00:00 ET

Affected tickers:
  - SKM (bullish)

--- Post Analysis Summary ---
The thesis is an indirect exposure and stake revaluation catalyst with clear evidence.

--- Discussion Summary ---
Several comments debated the ownership and no major rebuttal invalidated the setup.

--- Fact Check ---
1. [SUPPORTED] SKM invested in Anthropic.
   Source: SKT press release — https://example.com/skt
2. [SUPPORTED] Anthropic valuation changed.
   Source: Anthropic announcement — https://example.com/anthropic
3. [SUPPORTED] SKM has disclosed related investment holdings.
   Source: Filing — https://example.com/filing

--- Original Post (Reddit selftext) ---
body"""


BAD_POST = """=== DD Post: Bad XYZ thesis ===
Reddit title: DD: XYZ too good
postId: 1bad | author: u/test | score: 10 | comments: 10
Analysis updated: 2026-05-13 11:00:00 ET

Affected tickers:
  - XYZ (bullish)

--- Post Analysis Summary ---
The thesis has major weaknesses and relies on unsupported claims.

--- Discussion Summary ---
Top comments strongly rebut the core claim.

--- Fact Check ---
1. [UNSUPPORTED] Main revenue claim.
2. [QUESTIONABLE] Valuation claim.

--- Original Post (Reddit selftext) ---
body"""


MORE_POST = """=== DD Post: Another SKM thesis ===
Reddit title: DD: SKM second look
postId: 1more | author: u/test | score: 50 | comments: 30
Analysis updated: 2026-05-13 12:00:00 ET

Affected tickers:
  - SKM (neutral)

--- Post Analysis Summary ---
The thesis adds supplier and beneficiary context for the same stake revaluation theme.

--- Discussion Summary ---
Discussion is active and mostly focused on verification.

--- Fact Check ---
1. [SUPPORTED] Related company investment exists.
   Source: Filing — https://example.com/second

--- Original Post (Reddit selftext) ---
body"""


def test_dd_collector_extracts_evidence_and_scores_quality():
    client = FakeSellTheNewsClient(
        {
            "get_dd_list": DD_LIST,
            ("get_dd_post", "1good"): GOOD_POST,
            ("get_dd_post", "1bad"): BAD_POST,
        }
    )

    candidates = collect_sellthenews_dd_candidates(client, max_posts=2)

    by_ticker = {candidate.ticker: candidate for candidate in candidates}
    assert by_ticker["SKM"].source == "sellthenews_wsb_dd"
    assert by_ticker["SKM"].tier in {"A", "B"}
    assert by_ticker["SKM"].source_signals[0].post_id == "1good"
    assert by_ticker["SKM"].source_signals[0].fact_check_status_counts["supported"] == 3
    assert by_ticker["SKM"].source_signals[0].source_urls == [
        "https://example.com/skt",
        "https://example.com/anthropic",
        "https://example.com/filing",
    ]
    assert by_ticker["XYZ"].tier == "Rejected"
    assert by_ticker["XYZ"].rejected_reason == "fact-check risk dominates supported evidence"


def test_dd_collector_merges_multiple_posts_for_same_ticker():
    client = FakeSellTheNewsClient(
        {
            "get_dd_list": DD_LIST,
            ("get_dd_post", "1good"): GOOD_POST,
            ("get_dd_post", "1bad"): BAD_POST,
            ("get_dd_post", "1more"): MORE_POST,
        }
    )

    candidates = collect_sellthenews_dd_candidates(client, max_posts=3)

    skm = next(candidate for candidate in candidates if candidate.ticker == "SKM")
    assert [signal.post_id for signal in skm.source_signals] == ["1good", "1more"]
    assert len(skm.source_signals) == 2

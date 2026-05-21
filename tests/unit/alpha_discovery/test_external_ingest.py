from __future__ import annotations

from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository
from tradingagents.alpha_discovery.service import AlphaDiscoveryService


class FakeClient:
    def call_tool(self, name, arguments):
        raise AssertionError("external ingest should not call MCP tools")


def test_external_ingest_persists_watchlist_candidates_and_filters_invalid_symbols(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_confirmation_enabled": False},
    )

    summary = service.ingest_external_candidates(
        [
            {
                "ticker": "NVDA",
                "headline": "GPU demand inflects again",
                "theme": "AI infrastructure",
                "evidence_summary": "Multiple watchlist articles point to AI capex acceleration.",
                "alpha_score": 0.81,
                "tier": "A",
                "direction_hint": "bullish",
                "article_url": "https://example.com/nvda",
                "published_at": "2026-05-19T10:00:00Z",
                "confirmation_sources": ["watchlist_article"],
                "risk_flags": ["crowded_theme"],
            },
            {
                "ticker": "SPY",
                "headline": "ETF mention should be filtered",
                "theme": "Index",
                "alpha_score": 0.7,
            },
        ],
        source="n8n_watchlist",
        max_candidates=10,
    )

    assert summary["accepted"] == 1
    assert summary["tickers"] == ["NVDA"]
    assert any(item["reason"] == "symbol_filter" for item in summary["skipped"])

    rows = repo.list_candidates(tiers=["A"], status="open")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["score_components"]["promotion_gate"] == "external_ingest"
    assert rows[0]["score_components"]["confirmation_sources"] == ["watchlist_article"]

    events = repo.list_events(batch_id=summary["batch_id"], limit=20)
    event_types = {event["event_type"] for event in events}
    assert "external_ingest_start" in event_types
    assert "external_candidate" in event_types
    assert "external_ingest_complete" in event_types

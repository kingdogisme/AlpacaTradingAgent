from __future__ import annotations

from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository
from tradingagents.alpha_discovery.research_articles import build_candidate_impacts, classify_research_article
from tradingagents.alpha_discovery.service import AlphaDiscoveryService


class FakeClient:
    def call_tool(self, name, arguments):
        raise AssertionError("n8n research ingest should not call MCP tools")


def _event(**overrides):
    event = {
        "event_type": "substack.feed_item.discovered",
        "event_id": "research-event-1",
        "run_id": "research-run-1",
        "source": {"id": "semianalysis", "name": "SemiAnalysis", "type": "rss", "url": "https://semianalysis.com/feed/"},
        "article": {
            "title": "OUST Equity Research Deep Dive",
            "canonical_url": "https://example.com/oust-dd",
            "published_at": "2026-05-19T10:00:00Z",
            "author": "Researcher",
            "excerpt": "Deep dive thesis with data, valuation, revenue, margin, risks, and variant view. Strong upside because physical AI lidar demand is new and mispriced.",
            "guid": "guid-1",
        },
        "analysis": {
            "summary_zh": "这是 OUST 深度研究：thesis、估值、风险、数据和新信息都明确，作者 high conviction 看多。",
            "companies_or_tickers": ["OUST", "Ouster"],
            "watch_items": ["订单", "毛利率"],
        },
        "meta": {"schema_version": "1.0"},
    }
    for key, value in overrides.items():
        event[key] = value
    return event


def test_single_ticker_dd_yields_primary_boost_and_research_confirmation():
    evidence = classify_research_article(_event())
    impacts = build_candidate_impacts(evidence)

    assert evidence.article_kind == "single_ticker_dd"
    assert evidence.primary_tickers == ["OUST"]
    assert impacts[0].ticker == "OUST"
    assert impacts[0].confirmation is True
    assert impacts[0].max_tier == "A"


def test_n8n_research_ingest_creates_candidate_signal_and_is_idempotent(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient())

    first = service.ingest_n8n_event(_event())
    second = service.ingest_n8n_event(_event())

    assert first["status"] == "accepted"
    assert first["deduped"] is False
    assert second["deduped"] is True
    assert first["enriched"]["candidate_impacts"][0]["ticker"] == "OUST"

    rows = repo.list_candidates(tiers=["A"], status="open", ticker="OUST")
    assert len(rows) == 1
    row = rows[0]
    assert row["score_components"]["research_article_count"] == 1
    assert "research_article" in row["score_components"]["confirmation_sources"]
    assert row["score_components"]["promotion_gate"] == "passed_research_dd_gate"

    signals = repo.list_source_signals(candidate_ids=[row["candidate_id"]])
    assert len(signals) == 1
    assert signals[0]["source"] == "research_article"

    articles = repo.list_research_articles(limit=10, ticker="OUST")
    assert len(articles) == 1
    assert articles[0]["event_id"] == "research-event-1"
    assert articles[0]["enriched"]["article_kind"] == "single_ticker_dd"
    assert articles[0]["linked_candidate_tickers"] == ["OUST"]
    assert articles[0]["linked_candidate_count"] == 1

    detail = repo.get_research_article("research-event-1")
    assert detail is not None
    assert detail["linked_candidates"][0]["ticker"] == "OUST"
    assert detail["linked_candidates"][0]["evidence_json"]["research_article"]["article_kind"] == "single_ticker_dd"


def test_thematic_dd_secondary_tickers_do_not_directly_promote_to_a():
    event = _event(
        article={
            "title": "Advanced Packaging Value Chain Theme",
            "canonical_url": "https://example.com/packaging-theme",
            "published_at": "2026-05-19T10:00:00Z",
            "author": "Researcher",
            "excerpt": "先进封装 value chain thematic DD mentions NVDA AMD TSM with data and risks.",
            "guid": "guid-2",
        },
        analysis={
            "summary_zh": "先进封装主题研究，价值链迁移，涉及 NVDA、AMD、TSM，但不是单一公司 DD。",
            "companies_or_tickers": [],
            "watch_items": ["CoWoS capacity"],
        },
    )
    evidence = classify_research_article(event)
    impacts = build_candidate_impacts(evidence)

    assert evidence.article_kind == "thematic_dd"
    assert all(impact.max_tier == "B" for impact in impacts)
    assert all(not impact.confirmation for impact in impacts)


def test_power_semis_theme_does_not_extract_single_letter_noise():
    event = _event(
        article={
            "title": "GPU power value chain migration",
            "canonical_url": "https://example.com/gpu-power",
            "published_at": "2026-05-20T10:00:00Z",
            "author": "Researcher",
            "excerpt": "SiC and GaN power devices move value toward grid equipment and GPU-side power delivery.",
            "guid": "guid-gpu-power",
        },
        analysis={
            "summary_zh": "AI 数据中心电源价值链迁移，涉及 NVTS、POWI、ON、VRT、ETN，但 SiC/GaN 不是全行业无脑利好。",
            "companies_or_tickers": ["NVTS", "POWI", "ON", "VRT", "ETN"],
            "watch_items": ["design win", "backlog"],
        },
    )

    evidence = classify_research_article(event)

    assert evidence.article_kind == "thematic_dd"
    assert evidence.secondary_tickers == []
    assert "C" not in evidence.primary_tickers
    assert "N" not in evidence.primary_tickers
    assert "V" not in evidence.primary_tickers


def test_infrastructure_terms_do_not_become_secondary_tickers():
    event = _event(
        article={
            "title": "NVDA earning call infrastructure readthrough",
            "canonical_url": "https://example.com/nvda-earning-call",
            "published_at": "2026-05-21T10:00:00Z",
            "author": "Researcher",
            "excerpt": "CPU, OEM, GPU, HBM, ASIC, CXL, and AIDC are infrastructure terms in this article.",
            "guid": "guid-nvda-earning-call",
        },
        analysis={
            "summary_zh": "英伟达财报电话会后机会拆解，涉及 CPU、OEM、GPU、HBM、ASIC、CXL、AIDC 等配套方向。",
            "companies_or_tickers": ["NVDA"],
            "watch_items": ["OEM demand", "CPU attach"],
        },
    )

    evidence = classify_research_article(event)

    assert evidence.primary_tickers == ["NVDA"]
    assert evidence.secondary_tickers == []


def test_news_digest_does_not_overboost_all_mentioned_tickers(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient())
    event = _event(
        event_id="digest-1",
        article={
            "title": "Weekly Earnings Roundup NVDA AMD MSFT META",
            "canonical_url": "https://example.com/digest",
            "published_at": "2026-05-19T10:00:00Z",
            "author": "Researcher",
            "excerpt": "roundup digest memo with many tickers",
            "guid": "guid-3",
        },
        analysis={"summary_zh": "周报汇总，不是深度 DD。", "companies_or_tickers": [], "watch_items": []},
    )

    result = service.ingest_n8n_event(event)

    assert result["enriched"]["article_kind"] == "news_digest"
    assert result["enriched"]["candidate_impacts"] == []
    assert repo.list_candidates(tiers=None, status="open") == []

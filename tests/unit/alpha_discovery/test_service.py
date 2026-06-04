from __future__ import annotations

from tradingagents.alpha_discovery.models import DiscoveryBatch, Handoff, OpportunityCandidate, Outcome, SourceSignal
from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository
from tradingagents.alpha_discovery.service import AlphaDiscoveryService


class FakeClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_wsb_analysis":
            return """## 4. Sector Heatmap
| Memory/Semiconductor | High | Bullish | MU, SOXL, WTI |
| Energy Services | High | Bullish | WTI, NINE |

## 5. Individual Stock Sentiment Analysis
MU 80+ Strongly Bullish
SOXL 20+ Bullish
WTI 30+ Bullish on crude oil inventory draw and Brent futures
NINE 15+ Bullish
"""
        if name == "get_stock_news":
            return "Total articles: 2\n- 2026-05-20 MU memory pricing and DRAM shortage confirms company-specific catalyst. " * 8
        if name == "search_news":
            return "Total articles: 2\n- 2026-05-20 MU memory pricing catalyst and DRAM shortage. " * 8
        if name == "get_live_news":
            return "Total articles: 2\n- 2026-05-20 MU DRAM pricing update. " * 8
        if name == "get_trump_posts":
            return "No posts found"
        raise AssertionError(name)


class BrokenClient:
    def call_tool(self, name, arguments):
        raise RuntimeError(f"{name} unavailable")


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, ticker, trade_date, analysts, config_overrides=None):
        self.calls.append((ticker, trade_date, analysts, config_overrides))
        return "run-1", "BUY", "high"


class FakePlanRunner(FakeRunner):
    def run(self, ticker, trade_date, analysts, config_overrides=None):
        self.calls.append((ticker, trade_date, analysts, config_overrides))
        return "run-plan", "BUY", "high", "tp_linked"


def test_discover_wsb_persists_candidate_and_excludes_etf(tmp_path):
    service = AlphaDiscoveryService(
        repository=AlphaDiscoveryRepository(tmp_path / "ad.sqlite"),
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_confirmation_enabled": False},
    )

    summary = service.discover(sources=["wsb"], max_candidates=10)
    rows = service.list_candidates(tiers=["B"], status="open")

    assert summary["tier_counts"]["B"] == 2
    assert rows[0]["ticker"] == "MU"
    tickers = {row["ticker"] for row in service.list_candidates(tiers=["A", "B", "C", "Rejected"], status="open")}
    assert "SOXL" not in tickers
    assert "WTI" not in tickers
    assert "NINE" in tickers


def test_discover_invalidates_old_bad_symbols_and_supersedes_duplicate_tickers(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("old-batch", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="old-batch-s",
            batch_id="old-batch",
            ticker="S",
            tier="A",
            alpha_score=0.89,
            opportunity_type="continuation",
            direction_hint="mixed",
            theme="S&P 500 breadth warning",
            catalyst="S&P 500 breadth warning",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="old-batch-mu",
            batch_id="old-batch",
            ticker="MU",
            tier="B",
            alpha_score=0.72,
            opportunity_type="continuation",
            direction_hint="bullish",
            theme="Memory",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_confirmation_enabled": False},
    )

    service.discover(sources=["wsb"], max_candidates=10)

    open_rows = service.list_candidates(tiers=None, status="open")
    invalidated = service.list_candidates(tiers=None, status="invalidated")
    superseded = service.list_candidates(tiers=None, status="superseded")

    assert "S" not in {row["ticker"] for row in open_rows}
    assert invalidated[0]["ticker"] == "S"
    assert invalidated[0]["score_components"]["promotion_gate"] == "invalidated_symbol_filter"
    assert any(row["ticker"] == "MU" for row in superseded)
    assert sum(1 for row in open_rows if row["ticker"] == "MU") == 1


def test_confirmation_gate_can_promote_confirmed_candidate_to_a(tmp_path):
    client = FakeClient()
    service = AlphaDiscoveryService(
        repository=AlphaDiscoveryRepository(tmp_path / "ad.sqlite"),
        sellthenews_client=client,
        config={"alpha_discovery_news_confirmation_enabled": True},
    )

    summary = service.discover(sources=["wsb"], max_candidates=10)
    rows = service.list_candidates(tiers=["A"], status="open")

    assert summary["tier_counts"]["A"] == 1
    assert rows[0]["ticker"] == "MU"
    assert "direct_news" in rows[0]["score_components"]["confirmation_sources"]
    assert [name for name, _ in client.calls].count("get_stock_news") == 2


def test_weak_social_evidence_does_not_promote_to_a(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-low",
            batch_id="batch-1",
            ticker="LOWM",
            tier="B",
            alpha_score=0.78,
            opportunity_type="continuation",
            direction_hint="mixed",
            theme="weak social theme",
            catalyst="weak catalyst",
            score_components={"social_heat": 0.65},
            source_signals=[
                SourceSignal(
                    "batch-1-low",
                    "sellthenews_wsb_analysis",
                    "mcp://test",
                    mentions=5,
                    evidence_json={"theme": "weak social theme"},
                )
            ],
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_news_confirmation_enabled": True},
    )

    service.promote_existing(tiers=["B"], max_candidates=5)
    row = repo.list_candidates(tiers=["B"], status="open")[0]

    assert row["ticker"] == "LOWM"
    assert row["score_components"]["promotion_gate"] == "blocked_weak_social_evidence"
    assert "weak_social_evidence" in row["risk_flags"]


def test_cron_run_dry_run_and_execute_handoff(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="A",
            alpha_score=0.9,
            opportunity_type="continuation",
            direction_hint="bullish",
            source_signals=[
                SourceSignal("batch-1-mu", "test", "mcp://test"),
            ],
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient(), config={"alpha_discovery_confirmation_enabled": False})

    dry_run = service.run_candidates(tier="A", max_symbols=1, execute=False)
    runner = FakeRunner()
    executed = service.run_candidates(
        tier="A",
        max_symbols=1,
        execute=True,
        trade_date="2026-05-13",
        graph_runner=runner,
    )

    assert dry_run[0]["run_status"] == "dry_run"
    assert runner.calls == [
        (
            "MU",
            "2026-05-13",
            ["market", "fundamentals", "news", "social", "macro"],
            {
                "trading_horizon": "position",
                "trading_mode": "investment",
                "episode_ledger_metadata": {
                    "source": "alpha_discovery",
                    "ad_candidate_id": "batch-1-mu",
                    "ad_batch_id": "batch-1",
                    "ad_tier": "A",
                    "ad_alpha_score": 0.9,
                    "ad_opportunity_type": "continuation",
                    "ad_direction_hint": "bullish",
                },
            },
        )
    ]
    assert executed[0]["run_id"] == "run-1"
    assert repo.recent_handoffs("MU", since_iso="2026-05-13T00:00:00Z")


def test_cron_run_execute_records_plan_id_on_handoff(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="A",
            alpha_score=0.9,
            opportunity_type="continuation",
            direction_hint="bullish",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient(), config={"alpha_discovery_confirmation_enabled": False})

    executed = service.run_candidates(
        tier="A",
        max_symbols=1,
        execute=True,
        trade_date="2026-05-13",
        graph_runner=FakePlanRunner(),
    )

    handoff = repo.recent_handoffs("MU", since_iso="2026-05-13T00:00:00Z")[0]
    assert executed[0]["plan_id"] == "tp_linked"
    assert handoff["plan_id"] == "tp_linked"


def test_run_candidates_can_filter_specific_ticker(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    for ticker, score in (("BABA", 0.95), ("FIG", 0.9)):
        repo.upsert_candidate(
            OpportunityCandidate(
                candidate_id=f"batch-1-{ticker.lower()}",
                batch_id="batch-1",
                ticker=ticker,
                tier="A",
                alpha_score=score,
                opportunity_type="continuation",
                direction_hint="bullish",
            ),
            updated_at="2026-05-13T20:00:00Z",
        )
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_confirmation_enabled": False},
    )
    runner = FakeRunner()

    executed = service.run_candidates(
        tier="A",
        max_symbols=1,
        execute=True,
        trade_date="2026-05-13",
        graph_runner=runner,
        ticker="FIG",
    )

    assert runner.calls[0][0:3] == ("FIG", "2026-05-13", ["market", "fundamentals", "news", "social", "macro"])
    assert executed[0]["ticker"] == "FIG"


def test_cooldown_blocks_duplicate_execute(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="A",
            alpha_score=0.9,
            opportunity_type="continuation",
            direction_hint="bullish",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient(), config={"alpha_discovery_confirmation_enabled": False})
    runner = FakeRunner()

    service.run_candidates(tier="A", max_symbols=1, execute=True, trade_date="2026-05-13", graph_runner=runner)
    blocked = service.run_candidates(tier="A", max_symbols=1, execute=True, trade_date="2026-05-13", graph_runner=runner)

    assert blocked[0]["run_status"] == "cooldown"
    assert len(runner.calls) == 1


def test_daily_limit_blocks_after_configured_runs(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="A",
            alpha_score=0.9,
            opportunity_type="continuation",
            direction_hint="bullish",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={
            "alpha_discovery_confirmation_enabled": False,
            "alpha_discovery_full_ata_cooldown_hours": 0,
            "alpha_discovery_max_full_ata_runs_per_day": 1,
        },
    )
    runner = FakeRunner()

    service.run_candidates(tier="A", max_symbols=1, execute=True, trade_date="2026-05-13", graph_runner=runner)
    blocked = service.run_candidates(tier="A", max_symbols=1, execute=True, trade_date="2026-05-13", graph_runner=runner)

    assert blocked[0]["run_status"] == "daily_limit"
    assert len(runner.calls) == 1


def test_global_daily_budget_blocks_extra_execute(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    for ticker in ("MU", "NVDA"):
        repo.upsert_candidate(
            OpportunityCandidate(
                candidate_id=f"batch-1-{ticker.lower()}",
                batch_id="batch-1",
                ticker=ticker,
                tier="A",
                alpha_score=0.9,
                opportunity_type="continuation",
                direction_hint="bullish",
            ),
            updated_at="2026-05-13T20:00:00Z",
        )
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={
            "alpha_discovery_confirmation_enabled": False,
            "alpha_discovery_full_ata_cooldown_hours": 0,
            "alpha_discovery_max_full_ata_runs_per_day": 5,
            "alpha_discovery_default_ata_daily_budget": 1,
        },
    )
    runner = FakeRunner()

    results = service.run_candidates(tier="A", max_symbols=2, execute=True, trade_date="2026-05-13", graph_runner=runner)

    assert [row["run_status"] for row in results] == ["executed", "daily_budget"]
    assert len(runner.calls) == 1


def test_basket_report_summarizes_tiers_and_confirmations(tmp_path):
    service = AlphaDiscoveryService(
        repository=AlphaDiscoveryRepository(tmp_path / "ad.sqlite"),
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_news_confirmation_enabled": True},
    )

    service.discover(sources=["wsb"], max_candidates=10)
    report = service.basket_report()

    assert report["by_tier"]["A"] == 1
    assert report["by_source"]["direct_news"] == 1
    assert report["confirmation_coverage"]["confirmed_candidates"] == 1
    assert "MU" in report["by_ticker"]


def test_discover_writes_structured_events_for_debugging(tmp_path):
    service = AlphaDiscoveryService(
        repository=AlphaDiscoveryRepository(tmp_path / "ad.sqlite"),
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_news_confirmation_enabled": True},
    )

    summary = service.discover(sources=["wsb"], max_candidates=10)
    events = service.list_events(batch_id=summary["batch_id"], limit=50)

    event_types = {event["event_type"] for event in events}
    assert {"discover_start", "collector_complete", "dedupe_complete", "confirmation_complete", "score_candidate", "discover_complete"} <= event_types
    assert any(event["ticker"] == "MU" and event["payload_json"]["tier"] == "A" for event in events)


def test_discover_soft_fails_broken_collector_and_records_health(tmp_path):
    service = AlphaDiscoveryService(
        repository=AlphaDiscoveryRepository(tmp_path / "ad.sqlite"),
        sellthenews_client=BrokenClient(),
    )

    summary = service.discover(sources=["wsb"], max_candidates=10)
    events = service.list_events(batch_id=summary["batch_id"], status="error", limit=20)
    health = service.health_report()

    assert summary["raw_discoveries"] == 0
    assert any(event["event_type"] == "collector_failed" for event in events)
    assert any(event["event_type"] == "mcp_tool_call" for event in events)
    assert health["status"] == "degraded"
    assert health["latest_batches"][0]["status"] == "completed"


def test_phase2_optional_confirmation_collectors_are_called(tmp_path):
    client = FakeClient()
    service = AlphaDiscoveryService(
        repository=AlphaDiscoveryRepository(tmp_path / "ad.sqlite"),
        sellthenews_client=client,
        config={
            "alpha_discovery_news_confirmation_enabled": True,
            "alpha_discovery_search_news_confirmation_enabled": True,
            "alpha_discovery_live_news_confirmation_enabled": True,
            "alpha_discovery_policy_social_confirmation_enabled": True,
        },
    )

    service.discover(sources=["wsb"], max_candidates=10)

    call_names = [name for name, _ in client.calls]
    assert "get_stock_news" in call_names
    assert "search_news" in call_names
    assert "get_live_news" in call_names
    assert "get_trump_posts" in call_names


def test_cron_confirm_rechecks_existing_candidates_and_persists_promotion(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="B",
            alpha_score=0.78,
            opportunity_type="continuation",
            direction_hint="bullish",
            theme="Memory/Semiconductor",
            catalyst="memory pricing catalyst",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    service = AlphaDiscoveryService(
        repository=repo,
        sellthenews_client=FakeClient(),
        config={"alpha_discovery_news_confirmation_enabled": True},
    )

    summary = service.promote_existing(tiers=["B"], max_candidates=5)

    assert summary["promoted_to_a"] == ["MU"]
    assert repo.list_candidates(tiers=["A"], status="open")[0]["ticker"] == "MU"
    assert service.list_events(batch_id=summary["batch_id"], event_type="confirm_candidate", limit=5)


def test_basket_report_includes_outcome_hit_rates(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="A",
            alpha_score=0.92,
            opportunity_type="continuation",
            direction_hint="bullish",
            theme="Memory/Semiconductor",
            score_components={"confirmation_sources": ["direct_news"]},
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    repo.upsert_outcome(
        Outcome(
            candidate_id="batch-1-mu",
            horizon_days=3,
            raw_return=0.06,
            benchmark_return=0.01,
            alpha_return=0.05,
            mfe=0.07,
            mae=-0.01,
            resolved_at="2026-05-16T20:00:00Z",
        )
    )
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient())

    report = service.basket_report()

    assert report["source_hit_rates"]["direct_news"]["3"]["hit_rate"] == 1.0
    assert report["theme_hit_rates"]["Memory/Semiconductor"]["3"]["avg_alpha_return"] == 0.05


def test_evaluation_report_separates_ata_false_negative_and_shadow_hits(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-mu",
            batch_id="batch-1",
            ticker="MU",
            tier="A",
            alpha_score=0.92,
            opportunity_type="continuation",
            direction_hint="bullish",
            theme="Memory",
            score_components={"confirmation_sources": ["direct_news"]},
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-nvda",
            batch_id="batch-1",
            ticker="NVDA",
            tier="B",
            alpha_score=0.72,
            opportunity_type="continuation",
            direction_hint="bullish",
            theme="AI",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-xyz",
            batch_id="batch-1",
            ticker="XYZ",
            tier="Rejected",
            alpha_score=0.22,
            opportunity_type="avoid",
            direction_hint="avoid",
            theme="Pump-like DD",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )
    repo.upsert_handoff(
        Handoff(
            candidate_id="batch-1-mu",
            run_id="run-1",
            status="completed",
            executed_at="2026-05-13T21:00:00Z",
            ata_final_signal="HOLD",
        )
    )
    repo.upsert_outcome(
        Outcome("batch-1-mu", 3, 0.06, 0.01, 0.05, 0.07, -0.01, "2026-05-16T20:00:00Z")
    )
    repo.upsert_outcome(
        Outcome("batch-1-nvda", 3, 0.04, 0.01, 0.03, 0.05, -0.01, "2026-05-16T20:00:00Z")
    )
    repo.upsert_outcome(
        Outcome("batch-1-xyz", 3, -0.04, 0.01, -0.05, 0.01, -0.08, "2026-05-16T20:00:00Z")
    )
    service = AlphaDiscoveryService(repository=repo, sellthenews_client=FakeClient())

    report = service.evaluation_report()

    assert report["confusion_matrix"]["ad_selected_ata_rejected_alpha_positive"] == 1
    assert report["confusion_matrix"]["shadow_B_alpha_positive"] == 1
    assert report["confusion_matrix"]["shadow_Rejected_alpha_negative"] == 1
    assert any(row["ticker"] == "MU" for row in report["actual_performance"]["alpha_positive"])
    assert any(row["ticker"] == "XYZ" for row in report["actual_performance"]["alpha_negative"])

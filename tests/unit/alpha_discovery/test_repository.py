from __future__ import annotations

from tradingagents.alpha_discovery.models import (
    DiscoveryBatch,
    DiscoveryEvent,
    Handoff,
    OpportunityCandidate,
    Outcome,
    SourceSignal,
)
from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository


def test_repository_persists_batch_candidate_signal_handoff_and_outcome(tmp_path):
    repo = AlphaDiscoveryRepository(tmp_path / "ad.sqlite")
    batch = DiscoveryBatch(
        batch_id="batch-1",
        source="wsb,dd",
        generated_at="2026-05-13T20:00:00Z",
        config_json={"source": "test"},
    )
    repo.upsert_batch(batch)
    repo.update_batch_status("batch-1", "completed")
    assert repo.list_batches(limit=1)[0]["status"] == "completed"
    assert repo.list_batches(limit=1)[0]["config_json"]["source"] == "test"

    candidate = OpportunityCandidate(
        candidate_id="batch-1-skm",
        batch_id="batch-1",
        ticker="SKM",
        tier="A",
        alpha_score=0.82,
        opportunity_type="second_order",
        direction_hint="bullish",
        theme="WSB DD",
        catalyst="Anthropic stake revaluation",
        discovered_at="2026-05-13T20:00:00Z",
        score_components={"social_heat": 0.6, "confirmation_sources": ["direct_news"]},
        source_signals=[
            SourceSignal(
                candidate_id="batch-1-skm",
                source="sellthenews_wsb_dd",
                raw_artifact_id="mcp://sellthenews/dd/1abc",
                sentiment="bullish",
                evidence_json={"supported": 3},
            )
        ],
    )

    repo.upsert_candidate(candidate, updated_at="2026-05-13T20:00:01Z")
    rows = repo.list_candidates(tiers=["A"], status="open")

    assert rows[0]["candidate_id"] == "batch-1-skm"
    assert rows[0]["discovered_at"] == "2026-05-13T20:00:00Z"
    assert rows[0]["score_components"]["social_heat"] == 0.6
    assert rows[0]["recommended_analysts"] == ["market", "social", "news", "macro"]

    repo.upsert_handoff(
        Handoff(
            candidate_id="batch-1-skm",
            run_id="run-1",
            status="completed",
            executed_at="2026-05-13T20:10:00Z",
            ata_final_signal="BUY",
        )
    )
    assert repo.recent_handoffs("SKM", since_iso="2026-05-13T00:00:00Z")[0]["run_id"] == "run-1"
    assert repo.recent_handoffs_all(since_iso="2026-05-13T00:00:00Z")[0]["ticker"] == "SKM"

    repo.upsert_outcome(
        Outcome(
            candidate_id="batch-1-skm",
            horizon_days=5,
            raw_return=0.05,
            benchmark_return=0.01,
            alpha_return=0.04,
            mfe=0.07,
            mae=-0.02,
            resolved_at="2026-05-20T20:00:00Z",
        )
    )
    assert repo.list_source_signals(candidate_ids=["batch-1-skm"])[0]["evidence_json"]["supported"] == 3
    assert repo.get_source_signals("batch-1-skm")[0].source == "sellthenews_wsb_dd"
    assert repo.list_outcomes(status="open")[0]["alpha_return"] == 0.04

    event_id = repo.insert_event(
        DiscoveryEvent(
            event_id=None,
            event_time="2026-05-13T20:00:02Z",
            event_type="score_candidate",
            batch_id="batch-1",
            candidate_id="batch-1-skm",
            ticker="SKM",
            source="sellthenews_wsb_dd",
            status="ok",
            payload_json={"tier": "A"},
            duration_ms=12,
        )
    )
    events = repo.list_events(batch_id="batch-1", limit=10)
    assert events[0]["event_id"] == event_id
    assert events[0]["payload_json"]["tier"] == "A"

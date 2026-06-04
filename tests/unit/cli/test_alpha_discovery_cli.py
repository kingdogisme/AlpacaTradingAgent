from __future__ import annotations

from cli.main import _record_ad_handoff_for_ticker
from tradingagents.alpha_discovery.models import DiscoveryBatch, OpportunityCandidate
from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository


def test_record_ad_handoff_for_ticker_uses_dict_rows(tmp_path):
    db_path = tmp_path / "ad.sqlite"
    repo = AlphaDiscoveryRepository(db_path)
    repo.upsert_batch(DiscoveryBatch("batch-1", "test", "2026-05-13T20:00:00Z"))
    repo.upsert_candidate(
        OpportunityCandidate(
            candidate_id="batch-1-fig",
            batch_id="batch-1",
            ticker="FIG",
            tier="A",
            alpha_score=0.9,
            opportunity_type="continuation",
            direction_hint="bullish",
        ),
        updated_at="2026-05-13T20:00:00Z",
    )

    candidate_id = _record_ad_handoff_for_ticker(
        ticker="FIG",
        run_id="run-fig",
        final_signal="HOLD",
        confidence="medium",
        plan_id="tp_fig",
        config={"alpha_discovery_db_path": str(db_path)},
    )

    assert candidate_id == "batch-1-fig"
    handoff = repo.recent_handoffs("FIG", since_iso="2026-05-13T00:00:00Z")[0]
    assert handoff["run_id"] == "run-fig"
    assert handoff["plan_id"] == "tp_fig"

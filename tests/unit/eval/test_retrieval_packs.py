from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.indexing import build_retrieval_pack, build_run_index
from tradingagents.eval.models import LayerEvaluationResultRecord, LayerEvaluationTargetRecord


def _seed_run(ledger: EpisodeLedger, tmp_path: Path, run_id: str, symbol: str = "AAPL") -> None:
    audit_path = tmp_path / f"{run_id}.json"
    audit_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "symbol": symbol,
                "trade_date": "2026-05-20",
                "events": [
                    {
                        "timestamp": "2026-05-20T12:00:00Z",
                        "type": "tool_call",
                        "payload": {
                            "tool_name": "get_alpaca_data",
                            "agent_type": "market",
                            "inputs": {"symbol": symbol},
                            "status": "degraded",
                            "quality_details": {
                                "data_quality": {
                                    "status": "warn",
                                    "source_id": "alpaca_bars",
                                    "provider": "Alpaca",
                                    "dataset_type": "price_bars",
                                    "freshness": "warn",
                                    "accuracy": "unknown",
                                    "completeness": "pass",
                                    "flags": ["fallback_used"],
                                    "criticality": "critical",
                                    "artifact_ref": "tool_call:1",
                                    "output_preview": "preview",
                                }
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    final_state = {
        "final_trade_decision": "**Action**: HOLD\n**Confidence**: medium\nFINAL TRANSACTION PROPOSAL: **HOLD**",
        "trading_horizon": "position",
    }
    ledger.start_episode(run_id, symbol, "2026-05-20", {"prompt_version": "v1", "online_tools": False}, ["market"])
    ledger.complete_episode(run_id, final_state, "HOLD", str(audit_path))
    build_run_index(ledger, run_id)


def test_risk_review_pack_has_stable_refs_and_no_raw_output(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_run(ledger, tmp_path, "run-1")

    pack = build_retrieval_pack(ledger, pack_type="risk_review", run_id="run-1")

    assert pack["pack_id"] == "retrieval_pack:run-1:risk_review:v1"
    assert pack["summary"]["quality_status"] == "warn"
    assert pack["items"][0]["source_ref"] == "run_index:run-1"
    assert any(item["source_ref"] == "tool_call:1" for item in pack["items"])
    assert "raw output" not in json.dumps(pack)


def test_ticker_horizon_pack_summarizes_recent_runs(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _seed_run(ledger, tmp_path, "run-1")
    _seed_run(ledger, tmp_path, "run-2")

    pack = build_retrieval_pack(
        ledger,
        pack_type="ticker_horizon",
        symbol="AAPL",
        horizon="position",
        limit=5,
    )

    assert pack["summary"]["runs"] == 2
    assert pack["summary"]["action_distribution"] == {"HOLD": 2}
    assert all(item["item_id"].startswith("pack_item:") for item in pack["items"])


def test_layer_eval_pack_scopes_records_by_layer_and_artifact(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.upsert_layer_evaluation_target(
        LayerEvaluationTargetRecord(
            target_id="target-decision",
            layer="decision",
            target_type="investment_decision",
            symbol="NVDA",
            anchor_date="2026-06-06",
            decision_id="dec-1",
            horizon="position",
        )
    )
    ledger.upsert_layer_evaluation_record(
        LayerEvaluationResultRecord(
            evaluation_id="eval-decision",
            target_id="target-decision",
            layer="decision",
            evaluator_name="decision_contract_grader",
            status="warn",
            failure_tags=["missing_trigger"],
        )
    )

    pack = build_retrieval_pack(
        ledger,
        pack_type="layer_eval",
        layer="decision",
        artifact_id="dec-1",
        limit=5,
    )

    assert pack["pack_id"] == "retrieval_pack:layer_eval:dec-1:v1"
    assert pack["summary"]["layer_distribution"] == {"decision": 1}
    assert pack["summary"]["target_type_distribution"] == {"investment_decision": 1}
    assert pack["items"][0]["payload"]["decision_id"] == "dec-1"

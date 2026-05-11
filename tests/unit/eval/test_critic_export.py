from __future__ import annotations

import json
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.critic import HeuristicCritic, critic_memory_candidate
from tradingagents.eval.export import export_jsonl
from tradingagents.eval.rewards import RewardResolver


class SyntheticPriceProvider:
    def fetch_return(self, symbol, start_date, holding_days):
        return {"AAPL": -0.05, "SPY": 0.01}.get(symbol)


def test_critic_due_only_creates_diagnostic_memory_candidate(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {"trading_horizon": "swing"}, ["market"])
    ledger.complete_episode(
        "run-1",
        {
            "final_trade_decision": "**Action**: BUY\nFINAL TRANSACTION PROPOSAL: **BUY**",
            "trading_mode": "investment",
            "trading_horizon": "swing",
        },
        "BUY",
        None,
    )
    RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider(),
        config={"eval_neutral_band_bps": {"swing": 100}},
    ).score_due_episodes(as_of="2026-01-20")

    episode = ledger.resolved_reward_episodes_without_critic("v1")[0]
    record = HeuristicCritic("v1").critique(episode)
    ledger.add_critic_record(record)
    ledger.add_memory_item(critic_memory_candidate(record))

    assert "wrong_direction" in ledger.list_critic_records("run-1")[0]["failure_tags"]
    assert ledger.list_memory_items(run_id="run-1")[0]["source"] == "critic"
    assert ledger.resolved_reward_episodes_without_critic("v1") == []


def test_export_jsonl_emits_joinable_records_without_raw_decision_text(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {"online_tools": False}, ["market"])
    ledger.complete_episode(
        "run-1",
        {
            "final_trade_decision": "**Action**: BUY\nFINAL TRANSACTION PROPOSAL: **BUY**",
            "trading_mode": "investment",
            "trading_horizon": "swing",
        },
        "BUY",
        None,
    )
    output = tmp_path / "export.jsonl"

    count = export_jsonl(ledger, output_path=output)
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert count >= 2
    assert {record["record_type"] for record in records} >= {"episode", "decision"}
    assert all(record["run_id"] == "run-1" for record in records)
    decision = next(record for record in records if record["record_type"] == "decision")
    assert decision["raw_text"].startswith("<redacted:")

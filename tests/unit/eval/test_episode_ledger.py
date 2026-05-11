from pathlib import Path

from tradingagents.eval import EpisodeLedger


FINAL_STATE = {
    "investment_plan": "**Recommendation**: BUY\n**Confidence**: medium\nFINAL TRANSACTION PROPOSAL: **BUY**",
    "trader_investment_plan": "**Action**: BUY\n**Confidence**: medium\nFINAL TRANSACTION PROPOSAL: **BUY**",
    "final_trade_decision": "**Action**: BUY\n**Confidence**: high\nFINAL TRANSACTION PROPOSAL: **BUY**",
    "trading_mode": "investment",
    "trading_horizon": "swing",
}


def test_episode_ledger_idempotent_status_transition_and_decisions(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")

    ledger.start_episode("run-1", "AAPL", "2026-01-02", {"quick_think_llm": "q"}, ["market"])
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {"quick_think_llm": "q2"}, ["market", "news"])
    episode = ledger.load_episode("run-1")

    assert episode is not None
    assert episode["status"] == "running"
    assert episode["config"]["quick_think_llm"] == "q2"
    assert episode["selected_analysts"] == ["market", "news"]

    ledger.complete_episode("run-1", FINAL_STATE, "BUY", "/tmp/audit.json")
    episode = ledger.load_episode("run-1")

    assert episode["status"] == "completed"
    assert episode["final_signal"] == "BUY"
    assert episode["audit_path"] == "/tmp/audit.json"
    assert len(episode["decisions"]) == 3
    assert [decision["stage"] for decision in episode["decisions"]] == [
        "research_manager",
        "trader",
        "final",
    ]


def test_episode_ledger_fail_transition(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {}, [])
    ledger.fail_episode("run-1", "boom")

    episode = ledger.load_episode("run-1")
    assert episode["status"] == "failed"
    assert episode["error_message"] == "boom"

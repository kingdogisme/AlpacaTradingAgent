from __future__ import annotations

from datetime import date
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.rewards import RewardResolver


class SyntheticPriceProvider:
    def __init__(self, returns):
        self.returns = returns

    def fetch_return(self, symbol: str, start_date: date, holding_days: int) -> float | None:
        return self.returns.get(symbol)


def _completed_episode(ledger: EpisodeLedger, run_id: str, symbol: str, action: str = "BUY"):
    ledger.start_episode(run_id, symbol, "2026-01-02", {"trading_horizon": "swing"}, ["market"])
    ledger.complete_episode(
        run_id,
        {
            "final_trade_decision": f"**Action**: {action}\n**Confidence**: high\nFINAL TRANSACTION PROPOSAL: **{action}**",
            "trading_mode": "investment",
            "trading_horizon": "swing",
        },
        action,
        None,
    )


def test_reward_resolver_scores_alpha_outperformance(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _completed_episode(ledger, "run-1", "AAPL", "BUY")
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": 0.05, "SPY": 0.01}),
        config={"eval_transaction_cost_bps": 10, "eval_neutral_band_bps": {"swing": 100}},
    )

    rewards = resolver.score_due_episodes(as_of="2026-01-20")

    assert len(rewards) == 1
    reward = rewards[0]
    assert reward.raw_return == 0.05
    assert reward.benchmark_return == 0.01
    assert round(reward.alpha_return, 4) == 0.04
    assert reward.oracle_label == "BUY"
    assert reward.classification_reward == 1
    assert reward.reward_scalar > 0


def test_reward_resolver_keeps_immature_episode_pending(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _completed_episode(ledger, "run-1", "AAPL", "BUY")
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": 0.05, "SPY": 0.01}),
    )

    assert resolver.score_due_episodes(as_of="2026-01-04") == []
    episode = ledger.load_episode("run-1")
    assert episode["rewards"][0]["reward_status"] == "not_mature"


def test_reward_resolver_handles_no_benchmark_crypto(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _completed_episode(ledger, "run-1", "BTC/USD", "HOLD")
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"BTC/USD": 0.002}),
        config={"eval_neutral_band_bps": {"swing": 100}},
    )

    rewards = resolver.score_due_episodes(as_of="2026-01-20")

    assert len(rewards) == 1
    assert rewards[0].benchmark_return is None
    assert rewards[0].alpha_return is None
    assert rewards[0].oracle_label == "HOLD"


def test_reward_resolver_marks_insufficient_data(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _completed_episode(ledger, "run-1", "AAPL", "BUY")
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": None, "SPY": 0.01}),
    )

    assert resolver.score_due_episodes(as_of="2026-01-20") == []
    episode = ledger.load_episode("run-1")
    assert episode["rewards"][0]["reward_status"] == "insufficient_data"
    assert episode["rewards"][0]["components_json"]["reason"] == "missing_raw_return"

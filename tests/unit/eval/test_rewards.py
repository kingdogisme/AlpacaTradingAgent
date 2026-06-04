from __future__ import annotations

from datetime import date
from pathlib import Path

from tradingagents.eval import EpisodeLedger
from tradingagents.eval.rewards import RewardResolver, benchmark_for


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
    assert reward.components_json["counterfactual_rewards"]["buy_next_open"]["action"] == "BUY"


def test_reward_resolver_records_veto_counterfactual(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    ledger.start_episode("run-1", "AAPL", "2026-01-02", {"trading_horizon": "swing"}, ["market"])
    ledger.complete_episode(
        "run-1",
        {
            "investment_plan": "**Recommendation**: BUY\nFINAL TRANSACTION PROPOSAL: **BUY**",
            "trader_investment_plan": "**Action**: BUY\nFINAL TRANSACTION PROPOSAL: **BUY**",
            "final_trade_decision": "**Action**: HOLD\nFINAL TRANSACTION PROPOSAL: **HOLD**",
            "trading_mode": "investment",
            "trading_horizon": "swing",
        },
        "HOLD",
        None,
    )
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": 0.05, "SPY": 0.01}),
        config={"eval_transaction_cost_bps": 10, "eval_neutral_band_bps": {"swing": 100}},
    )

    rewards = resolver.score_due_episodes(as_of="2026-01-20")

    counterfactuals = rewards[0].components_json["counterfactual_rewards"]
    assert counterfactuals["final_action"]["action"] == "HOLD"
    assert counterfactuals["risk_manager_veto"]["action"] == "BUY"
    assert counterfactuals["risk_manager_veto"]["pnl_reward"] > counterfactuals["final_action"]["pnl_reward"]


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


def test_reward_resolver_uses_regional_benchmark_map(tmp_path: Path):
    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    _completed_episode(ledger, "run-1", "7203.T", "BUY")
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"7203.T": 0.04, "^N225": 0.01}),
        config={
            "benchmark_map": {".T": "^N225", "": "SPY"},
            "eval_neutral_band_bps": {"swing": 100},
        },
    )

    rewards = resolver.score_due_episodes(as_of="2026-01-20")

    assert len(rewards) == 1
    assert rewards[0].benchmark_return == 0.01
    assert round(rewards[0].alpha_return, 4) == 0.03
    assert rewards[0].components_json["benchmark"] == "^N225"


def test_benchmark_override_preserves_crypto_behavior():
    config = {"benchmark_ticker": "QQQ", "benchmark_map": {".T": "^N225", "": "SPY"}}

    assert benchmark_for("7203.T", config) == "QQQ"
    assert benchmark_for("BTC/USD", config) is None
    assert benchmark_for("ETH/USD", config) == "BTC-USD"


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


def test_conditional_plan_action_falls_back_to_trade_plan_repository(tmp_path: Path):
    from tradingagents.trade_lifecycle import ConditionalTradePlan, TradePlanRepository

    ledger = EpisodeLedger(tmp_path / "eval.sqlite")
    trade_db = tmp_path / "trade.sqlite"
    ledger.start_episode(
        "run-1",
        "AAPL",
        "2026-01-02",
        {"trading_horizon": "swing", "trade_lifecycle_db_path": str(trade_db)},
        ["market"],
    )
    ledger.complete_episode(
        "run-1",
        {
            "trader_investment_plan": "**Action**: BUY\nFINAL TRANSACTION PROPOSAL: **BUY**",
            "final_trade_decision": "**Action**: HOLD\nFINAL TRANSACTION PROPOSAL: **HOLD**",
            "trading_mode": "investment",
            "trading_horizon": "swing",
        },
        "HOLD",
        None,
    )
    TradePlanRepository(trade_db).upsert_plan(
        ConditionalTradePlan(
            plan_id="plan-1",
            symbol="AAPL",
            action="BUY",
            trigger={"type": "market"},
            invalidation={"price_below": 95.0},
            valid_until="2026-02-01T00:00:00Z",
            source_run_id="run-1",
            horizon="swing",
        )
    )
    resolver = RewardResolver(
        ledger,
        price_provider=SyntheticPriceProvider({"AAPL": 0.05, "SPY": 0.01}),
        config={"eval_transaction_cost_bps": 10, "eval_neutral_band_bps": {"swing": 100}},
    )

    rewards = resolver.score_due_episodes(as_of="2026-01-20")

    assert rewards[0].components_json["counterfactual_rewards"]["follow_conditional_plan"]["action"] == "BUY"

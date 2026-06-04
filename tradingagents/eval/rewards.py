from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Protocol

import yfinance as yf

from tradingagents.dataflows.benchmarks import benchmark_for_symbol

from .ledger import EpisodeLedger
from .models import RewardRecordV1


@dataclass(frozen=True)
class RewardResolveResult:
    status: str
    holding_days: int
    reward: RewardRecordV1 | None = None
    components: dict | None = None


class PriceProvider(Protocol):
    def fetch_return(self, symbol: str, start_date: date, holding_days: int) -> float | None:
        ...


class YFinancePriceProvider:
    def fetch_return(self, symbol: str, start_date: date, holding_days: int) -> float | None:
        yf_symbol = yahoo_symbol(symbol)

        end_date = start_date + timedelta(days=holding_days + 7)
        try:
            data = yf.download(
                yf_symbol,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                progress=False,
                auto_adjust=True,
                actions=False,
                threads=False,
            )
        except Exception:
            return None
        if data is None or data.empty or "Close" not in data:
            return None
        close = data["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        close = close.dropna()
        if len(close) < 2:
            return None
        start_price = float(close.iloc[0])
        end_price = float(close.iloc[-1])
        if start_price == 0:
            return None
        return (end_price / start_price) - 1.0


def default_holding_days(horizon: str | None, config: dict | None = None) -> int:
    cfg = config or {}
    if cfg.get("memory_outcome_holding_days") is not None:
        return int(cfg["memory_outcome_holding_days"])
    return {"swing": 5, "position": 63, "trend": 126}.get(str(horizon or "swing").lower(), 5)


def neutral_band(horizon: str | None, config: dict | None = None) -> float:
    cfg = config or {}
    bands = cfg.get("eval_neutral_band_bps") or {"swing": 100, "position": 300, "trend": 500}
    bps = bands.get(str(horizon or "swing").lower(), bands.get("swing", 100))
    return float(bps) / 10000.0


def benchmark_for(symbol: str, config: dict | None = None) -> str | None:
    return benchmark_for_symbol(symbol, config)


def is_crypto_symbol(symbol: str) -> bool:
    raw = str(symbol or "").upper()
    base = crypto_base(raw)
    return "/" in raw or "-" in raw or raw.endswith(("USD", "USDT", "USDC")) or base in {
        "BTC",
        "ETH",
        "ADA",
        "SOL",
        "DOGE",
        "MATIC",
        "AVAX",
        "DOT",
        "LINK",
        "UNI",
        "LTC",
        "BCH",
        "XRP",
        "ATOM",
    }


def crypto_base(symbol: str) -> str:
    raw = str(symbol or "").upper().replace("/", "-")
    if "-" in raw:
        return raw.split("-")[0]
    for suffix in ("USDT", "USDC", "USD"):
        if raw.endswith(suffix) and len(raw) > len(suffix):
            return raw[: -len(suffix)]
    return raw


def yahoo_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper()
    return f"{crypto_base(raw)}-USD" if is_crypto_symbol(raw) else raw.replace("/", "-")


def oracle_label_for(return_used: float, band: float, trading_mode: str | None) -> str:
    if return_used > band:
        return "LONG" if trading_mode == "trading" else "BUY"
    if return_used < -band:
        return "SHORT" if trading_mode == "trading" else "SELL"
    return "NEUTRAL" if trading_mode == "trading" else "HOLD"


def classification_reward(action: str | None, oracle_label: str) -> float:
    if not action:
        return 0.0
    if action == oracle_label:
        return 1.0
    neutral = {"HOLD", "NEUTRAL"}
    if action in neutral or oracle_label in neutral:
        return 0.0
    return -1.0


def pnl_reward_for(action: str | None, return_used: float, band: float, cost_bps: float) -> float:
    cost = float(cost_bps) / 10000.0
    if action in {"BUY", "LONG"}:
        return return_used - cost
    if action in {"SELL", "SHORT"}:
        return -return_used - cost
    if action in {"HOLD", "NEUTRAL"}:
        return 1.0 - min(abs(return_used) / band, 2.0)
    return 0.0


def counterfactual_rewards(
    *,
    final_action: str | None,
    return_used: float,
    band: float,
    cost_bps: float,
    trading_mode: str | None = None,
    analyst_action: str | None = None,
    risk_vetoed_action: str | None = None,
    conditional_plan_action: str | None = None,
) -> dict[str, dict[str, float | str | None]]:
    buy_action = "LONG" if str(trading_mode or "").lower() == "trading" else "BUY"
    scenarios = {
        "final_action": final_action,
        "buy_next_open": buy_action,
        "follow_conditional_plan": conditional_plan_action or final_action,
        "analyst_signal": analyst_action,
        "risk_manager_veto": risk_vetoed_action,
    }
    return {
        name: {
            "action": action,
            "pnl_reward": pnl_reward_for(action, return_used, band, cost_bps) if action else 0.0,
        }
        for name, action in scenarios.items()
    }


def clip_reward(value: float) -> float:
    return max(-1.0, min(1.0, value))


class RewardResolver:
    def __init__(
        self,
        ledger: EpisodeLedger,
        *,
        price_provider: PriceProvider | None = None,
        config: dict | None = None,
        trade_repository=None,
    ):
        self.ledger = ledger
        self.price_provider = price_provider or YFinancePriceProvider()
        self.config = config or {}
        self.trade_repository = trade_repository
        self.reward_version = self.config.get("eval_reward_version", "v1_directional_alpha")

    def score_due_episodes(self, *, as_of: str | None = None) -> list[RewardRecordV1]:
        as_of_date = self._parse_date(as_of) if as_of else date.today()
        resolved: list[RewardRecordV1] = []
        for episode in self.ledger.get_pending_reward_episodes(as_of=as_of):
            result = self.resolve_episode_status(episode, as_of_date=as_of_date)
            if result.reward is not None:
                self.ledger.upsert_reward(result.reward)
                resolved.append(result.reward)
                continue
            if result.status in {"not_mature", "insufficient_data", "failed"}:
                self.ledger.upsert_reward_status(
                    episode["run_id"],
                    self.reward_version,
                    result.status,
                    holding_days=result.holding_days,
                    components=result.components or {},
                    data_source=type(self.price_provider).__name__,
                )
        return resolved

    def resolve_episode(self, episode: dict, *, as_of_date: date) -> RewardRecordV1 | None:
        return self.resolve_episode_status(episode, as_of_date=as_of_date).reward

    def resolve_episode_status(self, episode: dict, *, as_of_date: date) -> RewardResolveResult:
        trade_date = self._parse_date(episode["trade_date"])
        horizon = episode.get("horizon") or "swing"
        holding_days = default_holding_days(horizon, self.config)
        if trade_date + timedelta(days=holding_days) > as_of_date:
            return RewardResolveResult(
                status="not_mature",
                holding_days=holding_days,
                components={
                    "reason": "holding_period_not_elapsed",
                    "matures_at": (trade_date + timedelta(days=holding_days)).isoformat(),
                    "as_of": as_of_date.isoformat(),
                },
            )

        symbol = episode["symbol"]
        raw_return = self.price_provider.fetch_return(symbol, trade_date, holding_days)
        if raw_return is None:
            return RewardResolveResult(
                status="insufficient_data",
                holding_days=holding_days,
                components={"reason": "missing_raw_return", "symbol": symbol},
            )

        benchmark = benchmark_for(symbol, self.config)
        benchmark_return = (
            self.price_provider.fetch_return(benchmark, trade_date, holding_days)
            if benchmark
            else None
        )
        if benchmark and benchmark_return is None:
            return RewardResolveResult(
                status="insufficient_data",
                holding_days=holding_days,
                components={
                    "reason": "missing_benchmark_return",
                    "symbol": symbol,
                    "benchmark": benchmark,
                    "raw_return": raw_return,
                },
            )
        alpha_return = raw_return - benchmark_return if benchmark_return is not None else None
        return_used = alpha_return if alpha_return is not None else raw_return
        band = neutral_band(horizon, self.config)
        mode = episode.get("trading_mode") or self._mode_from_action(episode.get("action"))
        oracle = oracle_label_for(return_used, band, mode)
        class_reward = classification_reward(episode.get("action"), oracle)
        pnl_reward = pnl_reward_for(
            episode.get("action"),
            return_used,
            band,
            float(self.config.get("eval_transaction_cost_bps", 10)),
        )
        cost_bps = float(self.config.get("eval_transaction_cost_bps", 10))
        full_episode = self.ledger.load_episode(episode["run_id"]) or episode
        counterfactuals = counterfactual_rewards(
            final_action=episode.get("action"),
            return_used=return_used,
            band=band,
            cost_bps=cost_bps,
            trading_mode=mode,
            analyst_action=_stage_action(full_episode, "trader") or _stage_action(full_episode, "research_manager"),
            risk_vetoed_action=_risk_vetoed_action(full_episode),
            conditional_plan_action=_conditional_plan_action(full_episode),
        )
        reward_scalar = clip_reward((class_reward + pnl_reward) / 2.0)

        reward = RewardRecordV1(
            run_id=episode["run_id"],
            reward_version=self.reward_version,
            holding_days=holding_days,
            raw_return=raw_return,
            benchmark_return=benchmark_return,
            alpha_return=alpha_return,
            oracle_label=oracle,
            classification_reward=class_reward,
            pnl_reward=pnl_reward,
            reward_scalar=reward_scalar,
            components_json={
                "action": episode.get("action"),
                "return_used": return_used,
                "neutral_band": band,
                "benchmark": benchmark,
                "transaction_cost_bps": cost_bps,
                "counterfactual_rewards": counterfactuals,
            },
            resolved_at=datetime.now(timezone.utc).isoformat(),
            data_source=type(self.price_provider).__name__,
        )
        return RewardResolveResult(status="resolved", holding_days=holding_days, reward=reward)

    @staticmethod
    def _parse_date(value: str) -> date:
        return datetime.strptime(str(value), "%Y-%m-%d").date()

    @staticmethod
    def _mode_from_action(action: str | None) -> str:
        return "trading" if action in {"LONG", "NEUTRAL", "SHORT"} else "investment"


def _stage_action(episode: dict, stage: str) -> str | None:
    for decision in episode.get("decisions", []):
        if decision.get("stage") == stage:
            return decision.get("action")
    return None


def _risk_vetoed_action(episode: dict) -> str | None:
    final = _stage_action(episode, "final")
    trader = _stage_action(episode, "trader")
    if final in {"HOLD", "NEUTRAL"} and trader in {"BUY", "LONG", "SELL", "SHORT"}:
        return trader
    return None


def _conditional_plan_action(episode: dict) -> str | None:
    run_id = episode.get("run_id")
    config = episode.get("config") if isinstance(episode.get("config"), dict) else {}
    action = _conditional_plan_action_from_trade_repository(run_id, config)
    if action:
        return action
    metadata = episode.get("metadata") if isinstance(episode.get("metadata"), dict) else {}
    plan = metadata.get("conditional_trade_plan") if isinstance(metadata.get("conditional_trade_plan"), dict) else {}
    action = str(plan.get("action") or "").upper()
    return action if action in {"BUY", "LONG", "SELL", "SHORT", "HOLD", "NEUTRAL"} else None


def _conditional_plan_action_from_trade_repository(run_id: str | None, config: dict | None = None) -> str | None:
    if not run_id:
        return None
    try:
        from tradingagents.trade_lifecycle import TradePlanRepository

        repository = TradePlanRepository((config or {}).get("trade_lifecycle_db_path"))
        plan = repository.get_plan_by_source_run_id(run_id)
    except Exception:
        return None
    if not plan:
        return None
    action = str(getattr(plan.action, "value", plan.action) or "").upper()
    return action if action in {"BUY", "LONG", "SELL", "SHORT", "HOLD", "NEUTRAL"} else None

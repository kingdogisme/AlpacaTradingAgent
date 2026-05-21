from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import yfinance as yf

from tradingagents.dataflows.benchmarks import benchmark_for_symbol

from .models import Outcome
from .repository import AlphaDiscoveryRepository


class PriceWindowProvider(Protocol):
    def fetch_prices(self, symbol: str, start_date: date, horizon_days: int) -> list[float]:
        ...


class YFinanceWindowProvider:
    def fetch_prices(self, symbol: str, start_date: date, horizon_days: int) -> list[float]:
        end_date = start_date + timedelta(days=horizon_days + 7)
        data = yf.download(
            symbol.replace("/", "-"),
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            progress=False,
            auto_adjust=True,
            actions=False,
            threads=False,
        )
        if data is None or data.empty or "Close" not in data:
            return []
        close = data["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        return [float(value) for value in close.dropna().tolist()]


class OutcomeResolver:
    def __init__(
        self,
        repository: AlphaDiscoveryRepository,
        *,
        price_provider: PriceWindowProvider | None = None,
        config: dict | None = None,
    ):
        self.repository = repository
        self.price_provider = price_provider or YFinanceWindowProvider()
        self.config = config or {}

    def resolve_open_candidates(
        self,
        *,
        as_of: str,
        horizons: list[int] | None = None,
    ) -> list[Outcome]:
        as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
        horizons = horizons or [1, 3, 5, 10]
        outcomes: list[Outcome] = []
        candidates = self.repository.list_candidates(tiers=None, status="open", limit=None)
        for candidate in candidates:
            start_date = _candidate_start_date(candidate)
            for horizon in horizons:
                if start_date + timedelta(days=horizon) > as_of_date:
                    continue
                raw_prices = self.price_provider.fetch_prices(candidate["ticker"], start_date, horizon)
                if len(raw_prices) < 2:
                    continue
                raw_return = (raw_prices[-1] / raw_prices[0]) - 1.0
                mfe = max((price / raw_prices[0]) - 1.0 for price in raw_prices)
                mae = min((price / raw_prices[0]) - 1.0 for price in raw_prices)
                benchmark = benchmark_for_symbol(candidate["ticker"], self.config)
                benchmark_return = None
                if benchmark:
                    benchmark_prices = self.price_provider.fetch_prices(benchmark, start_date, horizon)
                    if len(benchmark_prices) >= 2:
                        benchmark_return = (benchmark_prices[-1] / benchmark_prices[0]) - 1.0
                alpha_return = raw_return - benchmark_return if benchmark_return is not None else None
                outcome = Outcome(
                    candidate_id=candidate["candidate_id"],
                    horizon_days=horizon,
                    raw_return=raw_return,
                    benchmark_return=benchmark_return,
                    alpha_return=alpha_return,
                    mfe=mfe,
                    mae=mae,
                    resolved_at=datetime.now(timezone.utc).isoformat(),
                )
                self.repository.upsert_outcome(outcome)
                outcomes.append(outcome)
        return outcomes


def _candidate_start_date(candidate: dict) -> date:
    raw = str(candidate.get("discovered_at") or "")[:10]
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()

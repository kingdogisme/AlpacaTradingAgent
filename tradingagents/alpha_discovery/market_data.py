from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from tradingagents.dataflows.alpaca_utils import AlpacaUtils
from tradingagents.dataflows.freshness import date_age_days, is_fresh_date, parse_date


@dataclass
class AlpacaPriceVolumeProvider:
    """Price/volume confirmation source for Alpha Discovery promotion gates."""

    lookback_days: int = 10
    min_relative_volume: float = 1.5
    min_abs_1d_move: float = 0.025
    max_abs_5d_move: float = 0.25
    max_bar_age_days: int = 5

    def price_volume_confirmation(self, ticker: str) -> dict[str, Any]:
        end = datetime.now().date()
        start = end - timedelta(days=max(self.lookback_days * 3, 20))
        data = AlpacaUtils.get_stock_data(
            ticker,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            timeframe="1Day",
        )
        return price_volume_confirmation_from_bars(
            ticker,
            data,
            min_relative_volume=self.min_relative_volume,
            min_abs_1d_move=self.min_abs_1d_move,
            max_abs_5d_move=self.max_abs_5d_move,
            max_bar_age_days=self.max_bar_age_days,
        )


def price_volume_confirmation_from_bars(
    ticker: str,
    bars: pd.DataFrame,
    *,
    min_relative_volume: float = 1.5,
    min_abs_1d_move: float = 0.025,
    max_abs_5d_move: float = 0.25,
    max_bar_age_days: int = 5,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    if bars is None or bars.empty:
        return {"confirmed": False, "reason": "no price/volume bars"}

    df = bars.copy()
    df.columns = [str(col).lower() for col in df.columns]
    required = {"open", "close", "volume"}
    missing = sorted(required - set(df.columns))
    if missing:
        return {"confirmed": False, "reason": f"missing columns: {','.join(missing)}"}

    df = df.dropna(subset=["open", "close", "volume"]).tail(max(8, 6))
    if len(df) < 2:
        return {"confirmed": False, "reason": "insufficient bars"}

    latest_bar_date = _latest_bar_date(df)
    if latest_bar_date is not None and not is_fresh_date(
        latest_bar_date,
        as_of=as_of,
        max_age_days=max_bar_age_days,
        future_tolerance_days=1,
    ):
        return {
            "ticker": ticker,
            "confirmed": False,
            "reason": "stale price/volume bars",
            "latest_bar_date": latest_bar_date.isoformat(),
            "bar_age_days": date_age_days(latest_bar_date, as_of=as_of),
            "max_bar_age_days": max_bar_age_days,
        }

    latest = df.iloc[-1]
    previous = df.iloc[-2]
    prev_close = float(previous["close"])
    latest_open = float(latest["open"])
    latest_close = float(latest["close"])
    latest_volume = float(latest["volume"])
    if prev_close <= 0 or latest_open <= 0:
        return {"confirmed": False, "reason": "invalid prices"}

    prior_volume = df.iloc[:-1]["volume"].astype(float)
    avg_volume = float(prior_volume.tail(10).mean()) if not prior_volume.empty else 0.0
    relative_volume = latest_volume / avg_volume if avg_volume > 0 else None
    one_day_move = latest_close / prev_close - 1.0
    gap = latest_open / prev_close - 1.0

    first_close = float(df.iloc[max(0, len(df) - 6)]["close"])
    five_day_move = latest_close / first_close - 1.0 if first_close > 0 else 0.0
    overextended = abs(five_day_move) > max_abs_5d_move
    confirmed = (
        relative_volume is not None
        and relative_volume >= min_relative_volume
        and abs(one_day_move) >= min_abs_1d_move
        and not overextended
    )
    strength = 0.0
    if confirmed:
        strength = 0.12
        strength += min(max(relative_volume - min_relative_volume, 0.0) * 0.03, 0.06)
        strength += min(max(abs(one_day_move) - min_abs_1d_move, 0.0) * 1.2, 0.06)

    return {
        "ticker": ticker,
        "confirmed": confirmed,
        "relative_volume": round(relative_volume, 3) if relative_volume is not None else None,
        "gap": round(gap, 4),
        "one_day_move": round(one_day_move, 4),
        "five_day_move": round(five_day_move, 4),
        "overextended": overextended,
        "confirmation_strength": round(min(strength, 0.22), 3),
        "reason": "relative volume + 1d move" if confirmed else "below price/volume thresholds",
        "latest_bar_date": latest_bar_date.isoformat() if latest_bar_date else None,
    }


def _latest_bar_date(df: pd.DataFrame):
    if "timestamp" in df.columns:
        timestamps = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dropna()
        if not timestamps.empty:
            return timestamps.max().date()
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
        return df.index.max().date()
    index_value = df.index[-1] if len(df.index) else None
    if isinstance(index_value, (int, float)):
        return None
    parsed = parse_date(index_value)
    return parsed

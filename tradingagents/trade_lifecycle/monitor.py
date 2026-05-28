from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

import pandas as pd

from .models import MarketObservation, TradePlanEvent, TradePlanStatus
from .repository import TradePlanRepository
from .validator import PreTradeValidator, execute_validated_plan


class TradeMonitorService:
    def __init__(self, config: dict[str, Any] | None = None, repository: TradePlanRepository | None = None):
        self.config = config or {}
        self.repository = repository or TradePlanRepository(self.config.get("trade_lifecycle_db_path"))
        self.validator = PreTradeValidator(self.config)

    def run_forever(self, interval_seconds: int = 60, *, symbols: list[str] | None = None) -> None:
        while True:
            self.run_once(symbols=symbols)
            time.sleep(max(int(interval_seconds), 1))

    def run_once(self, *, symbols: list[str] | None = None) -> dict[str, Any]:
        expired = self.repository.expire_stale_plans(datetime.now(timezone.utc).isoformat())
        results: list[dict[str, Any]] = []
        for plan in self.repository.list_active_plans(symbols):
            observation = self._observe(plan.symbol)
            self.repository.append_event(
                TradePlanEvent(
                    plan_id=plan.plan_id,
                    event_type="monitor_observation",
                    payload=observation.model_dump(mode="json"),
                )
            )
            if not _trigger_met(plan, observation):
                results.append(
                    {
                        "plan_id": plan.plan_id,
                        "symbol": plan.symbol,
                        "passed": False,
                        "decision": "waiting",
                        "reasons": ["trigger not met"],
                    }
                )
                continue
            if not self._debounce_met(plan):
                results.append(
                    {
                        "plan_id": plan.plan_id,
                        "symbol": plan.symbol,
                        "passed": False,
                        "decision": "waiting",
                        "reasons": ["trigger debounce pending"],
                    }
                )
                continue
            current_position = self._current_position(plan.symbol)
            validation = self.validator.validate(
                plan,
                observation,
                account_info=self._account_info(),
                current_position=current_position,
            )
            self.repository.record_validation(validation)
            item = {
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "passed": validation.passed,
                "decision": validation.decision,
                "reasons": validation.reasons,
            }
            if not validation.passed:
                if validation.decision == "rejected":
                    self.repository.update_status(plan.plan_id, TradePlanStatus.REJECTED, reason="; ".join(validation.reasons))
                results.append(item)
                continue

            self.repository.update_status(plan.plan_id, TradePlanStatus.TRIGGERED, reason="monitor trigger passed validator")
            order_result = self._execute_plan(plan, validation, current_position=current_position)
            self.repository.append_event(
                TradePlanEvent(
                    plan_id=plan.plan_id,
                    event_type="order_result",
                    status="ok" if order_result.get("success") else "error",
                    message=order_result.get("message") or order_result.get("error") or "",
                    payload=order_result,
                )
            )
            self.repository.update_status(
                plan.plan_id,
                TradePlanStatus.EXECUTED if order_result.get("success") else TradePlanStatus.REJECTED,
                reason="paper order executed" if order_result.get("success") else "paper order failed",
            )
            item["order_result"] = order_result
            results.append(item)
        return {
            "expired": [plan.plan_id for plan in expired],
            "processed": results,
        }

    def _observe(self, symbol: str) -> MarketObservation:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        quote = AlpacaUtils.get_latest_quote(symbol)
        price = _quote_price(quote)
        now = datetime.now(timezone.utc)
        start = (now - pd.Timedelta(days=260)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        bars = AlpacaUtils.get_stock_data(symbol, start, end_date=end, timeframe="1Day")
        technical = _technical_snapshot(bars)
        if price <= 0:
            price = technical.get("price") or 0.0
        prev_close = technical.get("prev_close")
        gap_pct = None
        if prev_close and price:
            gap_pct = (price / prev_close) - 1
        return MarketObservation(
            symbol=symbol,
            price=float(price or 0.0),
            prev_close=prev_close,
            gap_pct=gap_pct,
            volume=technical.get("volume"),
            avg_volume=technical.get("avg_volume"),
            volume_ratio=technical.get("volume_ratio"),
            rsi_14=technical.get("rsi_14"),
            sma_50=technical.get("sma_50"),
            sma_200=technical.get("sma_200"),
            raw={"quote": quote, "technical": technical},
        )

    def _account_info(self) -> dict[str, Any]:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        return AlpacaUtils.get_account_info()

    def _current_position(self, symbol: str) -> str:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        return AlpacaUtils.get_current_position_state(symbol)

    def _execute_plan(self, plan, validation, *, current_position: str | None = None) -> dict[str, Any]:
        return execute_validated_plan(plan, validation, config=self.config, current_position=current_position)

    def _debounce_met(self, plan) -> bool:
        required = max(int(plan.trigger.debounce_observations or 1), 1)
        if required <= 1:
            return True
        self.repository.append_event(
            TradePlanEvent(
                plan_id=plan.plan_id,
                event_type="trigger_observed",
                status="waiting",
                message=f"trigger observation recorded for debounce {required}",
                payload={"required_observations": required},
            )
        )
        observed = [
            event for event in self.repository.list_events(plan.plan_id)
            if event["event_type"] == "trigger_observed"
        ]
        return len(observed) >= required


def _quote_price(quote: dict[str, Any]) -> float:
    bid = _safe_float(quote.get("bid_price"))
    ask = _safe_float(quote.get("ask_price"))
    if bid and ask:
        return (bid + ask) / 2
    return bid or ask or 0.0


def _technical_snapshot(df: pd.DataFrame | None) -> dict[str, float]:
    if df is None or df.empty:
        return {}
    prepared = df.copy()
    prepared.columns = [str(col).lower() for col in prepared.columns]
    if "close" not in prepared or len(prepared) < 2:
        return {}
    close = pd.to_numeric(prepared["close"], errors="coerce").dropna()
    volume = pd.to_numeric(prepared.get("volume"), errors="coerce").dropna() if "volume" in prepared else pd.Series(dtype=float)
    if len(close) < 2:
        return {}
    rsi = _rsi(close)
    sma_50 = close.rolling(50).mean()
    sma_200 = close.rolling(200).mean()
    avg_volume = volume.rolling(20).mean() if not volume.empty else pd.Series(dtype=float)
    last_volume = float(volume.iloc[-1]) if not volume.empty else None
    last_avg_volume = float(avg_volume.iloc[-1]) if len(avg_volume) and not pd.isna(avg_volume.iloc[-1]) else None
    return {
        "price": float(close.iloc[-1]),
        "prev_close": float(close.iloc[-2]),
        "volume": last_volume,
        "avg_volume": last_avg_volume,
        "volume_ratio": (last_volume / last_avg_volume) if last_volume and last_avg_volume else None,
        "rsi_14": float(rsi.iloc[-1]) if len(rsi) and not pd.isna(rsi.iloc[-1]) else None,
        "sma_50": float(sma_50.iloc[-1]) if len(sma_50) and not pd.isna(sma_50.iloc[-1]) else None,
        "sma_200": float(sma_200.iloc[-1]) if len(sma_200) and not pd.isna(sma_200.iloc[-1]) else None,
    }


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _trigger_met(plan, observation: MarketObservation) -> bool:
    trigger = plan.trigger
    price = observation.price
    hysteresis = max(trigger.hysteresis_pct or 0.0, 0.0)
    if trigger.type == "market":
        price_ok = True
    elif trigger.type == "price_above":
        price_ok = price >= float(trigger.price_above or 0) * (1 + hysteresis)
    elif trigger.type == "price_below":
        price_ok = price <= float(trigger.price_below or 0) * (1 - hysteresis)
    else:
        low = float(trigger.price_low or 0) * (1 + hysteresis)
        high = float(trigger.price_high or 0) * (1 - hysteresis)
        price_ok = low <= price <= high
    if not price_ok:
        return False
    if trigger.volume_min_ratio is not None and (
        observation.volume_ratio is None or observation.volume_ratio < trigger.volume_min_ratio
    ):
        return False
    if trigger.rsi_min is not None and (observation.rsi_14 is None or observation.rsi_14 < trigger.rsi_min):
        return False
    if trigger.rsi_max is not None and (observation.rsi_14 is None or observation.rsi_14 > trigger.rsi_max):
        return False
    if trigger.require_price_above_sma_50 and (
        observation.sma_50 is None or observation.price <= observation.sma_50
    ):
        return False
    if trigger.require_price_above_sma_200 and (
        observation.sma_200 is None or observation.price <= observation.sma_200
    ):
        return False
    return True

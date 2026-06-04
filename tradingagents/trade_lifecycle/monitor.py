from __future__ import annotations

from datetime import datetime, time as dt_time, timezone
import json
import subprocess
import time
from typing import Any
from urllib import request, error
from zoneinfo import ZoneInfo

import pandas as pd

from .models import MarketObservation, TradePlanEvent, TradePlanStatus
from .repository import TradePlanRepository
from .validator import PreTradeValidator, execute_validated_plan


class TradeMonitorService:
    def __init__(self, config: dict[str, Any] | None = None, repository: TradePlanRepository | None = None):
        self.config = config or {}
        self.repository = repository or TradePlanRepository(self.config.get("trade_lifecycle_db_path"))
        self.validator = PreTradeValidator(self.config)

    def run_forever(
        self,
        interval_seconds: int = 60,
        *,
        symbols: list[str] | None = None,
        respect_market_hours: bool | None = None,
        heartbeat: bool = True,
        max_iterations: int | None = None,
    ) -> None:
        iterations = 0
        while True:
            self.run_once(
                symbols=symbols,
                respect_market_hours=respect_market_hours,
                heartbeat=heartbeat,
            )
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return
            time.sleep(max(int(interval_seconds), 1))

    def _market_session_state(self, now: datetime) -> dict[str, Any]:
        fallback = market_session_state(now)
        if not bool(self.config.get("trade_monitor_use_alpaca_clock", True)):
            return fallback
        try:
            return self._alpaca_market_session_state(now, fallback=fallback)
        except Exception as exc:
            return {
                **fallback,
                "session_source": "local_time_fallback",
                "clock_error": str(exc),
                "clock_error_type": type(exc).__name__,
            }

    def _alpaca_market_session_state(self, now: datetime, *, fallback: dict[str, Any]) -> dict[str, Any]:
        from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client

        clock = get_alpaca_trading_client().get_clock()
        timestamp = _clock_datetime(getattr(clock, "timestamp", None), default=now)
        next_open = _clock_datetime(getattr(clock, "next_open", None), default=None)
        next_close = _clock_datetime(getattr(clock, "next_close", None), default=None)
        return {
            **fallback,
            "now_utc": timestamp.astimezone(timezone.utc).isoformat(),
            "now_et": timestamp.astimezone(ZoneInfo("America/New_York")).isoformat(),
            "is_regular_session": bool(getattr(clock, "is_open", False)),
            "session_source": "alpaca_clock",
            "next_open": next_open.isoformat() if next_open else None,
            "next_close": next_close.isoformat() if next_close else None,
        }

    def run_once(
        self,
        *,
        symbols: list[str] | None = None,
        respect_market_hours: bool | None = None,
        heartbeat: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        market_state = self._market_session_state(now)
        if respect_market_hours is None:
            respect_market_hours = bool(self.config.get("trade_monitor_respect_market_hours", False))
        if heartbeat:
            self._append_heartbeat(now, market_state, symbols=symbols)
        if respect_market_hours and not market_state["is_regular_session"]:
            return {
                "skipped": True,
                "skip_reason": "outside_regular_market_hours",
                "market_session": market_state,
                "expired": [],
                "processed": [],
            }
        expired = self.repository.expire_stale_plans(datetime.now(timezone.utc).isoformat())
        results: list[dict[str, Any]] = []
        for plan in [
            plan for plan in self.repository.list_active_plans(symbols)
            if plan.status == TradePlanStatus.ACTIVE
        ]:
            try:
                observation = self._observe(plan.symbol)
            except Exception as exc:
                self.repository.append_event(
                    TradePlanEvent(
                        plan_id=plan.plan_id,
                        event_type="monitor_observation_failed",
                        status="error",
                        message=str(exc),
                        payload={"error_type": type(exc).__name__},
                    )
                )
                results.append(
                    {
                        "plan_id": plan.plan_id,
                        "symbol": plan.symbol,
                        "passed": False,
                        "decision": "observation_failed",
                        "reasons": [str(exc)],
                    }
                )
                continue
            self.repository.append_event(
                TradePlanEvent(
                    plan_id=plan.plan_id,
                    event_type="monitor_observation",
                    payload=observation.model_dump(mode="json"),
                )
            )
            trigger_result = evaluate_trigger(plan, observation)
            if not trigger_result["met"]:
                self._reset_debounce(plan, observation)
                results.append(
                    {
                        "plan_id": plan.plan_id,
                        "symbol": plan.symbol,
                        "passed": False,
                        "decision": "waiting",
                        "reasons": trigger_result["reasons"] or ["trigger not met"],
                        "trigger_result": trigger_result,
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
            review_payload = {
                "matched_leg": trigger_result.get("matched_leg"),
                "trigger_result": trigger_result,
                "observation": observation.model_dump(mode="json"),
            }
            self.repository.update_status(
                plan.plan_id,
                TradePlanStatus.NEEDS_REVIEW,
                reason="monitor trigger met; manual trigger review required",
                payload=review_payload,
            )
            self.repository.append_event(
                TradePlanEvent(
                    plan_id=plan.plan_id,
                    event_type="trigger_review_required",
                    status="waiting",
                    message="Trigger met; awaiting execute/resize/cancel/supersede review.",
                    payload=review_payload,
                )
            )
            self._notify_review_required(plan, review_payload)
            results.append(
                {
                    "plan_id": plan.plan_id,
                    "symbol": plan.symbol,
                    "passed": False,
                    "decision": "needs_review",
                    "reasons": ["trigger met; manual review required"],
                    "trigger_result": trigger_result,
                }
            )
        return {
            "skipped": False,
            "market_session": market_state,
            "expired": [plan.plan_id for plan in expired],
            "processed": results,
        }

    def _append_heartbeat(self, now: datetime, market_state: dict[str, Any], *, symbols: list[str] | None) -> None:
        self.repository.append_monitor_event(
            event_type="monitor_heartbeat",
            status="ok",
            message="trade monitor heartbeat",
            payload={
                "observed_at": now.isoformat(),
                "market_session": market_state,
                "symbols": symbols or [],
            },
            created_at=now.isoformat(),
        )

    def _notify_review_required(self, plan, review_payload: dict[str, Any]) -> None:
        self._notify_review_webhook(plan, review_payload)
        self._notify_review_im(plan, review_payload)

    def _notify_review_webhook(self, plan, review_payload: dict[str, Any]) -> None:
        webhook_url = str(self.config.get("trade_monitor_review_webhook_url") or "").strip()
        if not webhook_url:
            return
        payload = {
            "event_type": "trigger_review_required",
            "plan_id": plan.plan_id,
            "symbol": plan.symbol,
            "action": plan.action.value,
            "status": TradePlanStatus.NEEDS_REVIEW.value,
            "review": review_payload,
        }
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = request.Request(
                webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            timeout = float(self.config.get("trade_monitor_webhook_timeout_seconds", 5))
            with request.urlopen(req, timeout=timeout) as response:
                status_code = getattr(response, "status", None) or getattr(response, "code", None)
            self.repository.append_monitor_event(
                event_type="trigger_review_notification",
                status="ok",
                message="trigger review notification sent",
                payload={"plan_id": plan.plan_id, "symbol": plan.symbol, "status_code": status_code},
            )
        except (OSError, ValueError, error.URLError) as exc:
            self.repository.append_monitor_event(
                event_type="trigger_review_notification",
                status="error",
                message=str(exc),
                payload={"plan_id": plan.plan_id, "symbol": plan.symbol, "error_type": type(exc).__name__},
            )

    def _notify_review_im(self, plan, review_payload: dict[str, Any]) -> None:
        channel = str(self.config.get("trade_monitor_review_im_channel") or "").strip()
        target = str(self.config.get("trade_monitor_review_im_target") or "").strip()
        if not channel or not target:
            return
        account = str(self.config.get("trade_monitor_review_im_account") or "").strip()
        openclaw_bin = str(self.config.get("trade_monitor_openclaw_bin") or "openclaw").strip() or "openclaw"
        timeout = float(self.config.get("trade_monitor_openclaw_timeout_seconds", 10))
        message = _format_review_im_message(plan, review_payload)
        cmd = [
            openclaw_bin,
            "message",
            "send",
            "--channel",
            channel,
            "--target",
            target,
            "--message",
            message,
            "--json",
        ]
        if account:
            cmd.extend(["--account", account])
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.repository.append_monitor_event(
                event_type="trigger_review_im_notification",
                status="error",
                message=str(exc),
                payload={
                    "plan_id": plan.plan_id,
                    "symbol": plan.symbol,
                    "channel": channel,
                    "account": account or None,
                    "target": target,
                    "error_type": type(exc).__name__,
                },
            )
            return
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        result_payload = _parse_json_output(stdout)
        status = "ok" if completed.returncode == 0 else "error"
        self.repository.append_monitor_event(
            event_type="trigger_review_im_notification",
            status=status,
            message="trigger review IM notification sent" if status == "ok" else stderr or stdout,
            payload={
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "channel": channel,
                "account": account or None,
                "target": target,
                "returncode": completed.returncode,
                "stdout": stdout[:2000],
                "stderr": stderr[:2000],
                "result": result_payload,
            },
        )

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
        observed = self._pending_trigger_count(plan.plan_id) + 1
        self.repository.append_event(
            TradePlanEvent(
                plan_id=plan.plan_id,
                event_type="trigger_observed",
                status="waiting",
                message=f"trigger observation recorded for debounce {required}",
                payload={"required_observations": required, "pending_observations": observed},
            )
        )
        return observed >= required

    def _reset_debounce(self, plan, observation: MarketObservation) -> None:
        if int(plan.trigger.debounce_observations or 1) <= 1:
            return
        self.repository.append_event(
            TradePlanEvent(
                plan_id=plan.plan_id,
                event_type="trigger_reset",
                status="waiting",
                message="trigger observation reset because condition was not continuously met",
                payload=observation.model_dump(mode="json"),
            )
        )

    def _pending_trigger_count(self, plan_id: str) -> int:
        count = 0
        for event in self.repository.list_events(plan_id):
            if event["event_type"] == "trigger_reset":
                count = 0
            elif event["event_type"] == "trigger_observed":
                count += 1
        return count


def _quote_price(quote: dict[str, Any]) -> float:
    bid = _safe_float(quote.get("bid_price"))
    ask = _safe_float(quote.get("ask_price"))
    if bid and ask:
        return (bid + ask) / 2
    return bid or ask or 0.0


def _format_review_im_message(plan, review_payload: dict[str, Any]) -> str:
    observation = review_payload.get("observation") or {}
    trigger_result = review_payload.get("trigger_result") or {}
    matched_leg = review_payload.get("matched_leg") or trigger_result.get("matched_leg") or {}
    price = observation.get("price")
    volume_ratio = observation.get("volume_ratio")
    lines = [
        "[TradingAgents] Trigger review required",
        f"Symbol: {plan.symbol}",
        f"Action: {plan.action.value}",
        f"Status: {TradePlanStatus.NEEDS_REVIEW.value}",
        f"Plan: {plan.plan_id}",
    ]
    if price is not None:
        lines.append(f"Price: {price}")
    if volume_ratio is not None:
        lines.append(f"Volume ratio: {volume_ratio}")
    if matched_leg:
        leg_index = matched_leg.get("leg_index")
        if leg_index is not None:
            lines.append(f"Matched trigger leg: {leg_index}")
        reasons = matched_leg.get("reasons") or []
        if reasons:
            lines.append(f"Trigger notes: {', '.join(str(reason) for reason in reasons)}")
    lines.append("Required review: execute / resize / cancel / supersede")
    return "\n".join(lines)


def _parse_json_output(output: str) -> dict[str, Any] | None:
    if not output:
        return None
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def market_session_state(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    eastern = current.astimezone(ZoneInfo("America/New_York"))
    regular_open = dt_time(9, 30)
    regular_close = dt_time(16, 0)
    is_weekday = eastern.weekday() < 5
    current_time = eastern.time()
    return {
        "now_utc": current.astimezone(timezone.utc).isoformat(),
        "now_et": eastern.isoformat(),
        "is_weekday": is_weekday,
        "regular_open": "09:30:00",
        "regular_close": "16:00:00",
        "is_regular_session": bool(is_weekday and regular_open <= current_time <= regular_close),
    }


def _clock_datetime(value: Any, *, default: datetime | None) -> datetime | None:
    if value is None:
        return default
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = pd.Timestamp(value).to_pydatetime()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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
    return bool(evaluate_trigger(plan, observation)["met"])


def evaluate_trigger(plan, observation: MarketObservation) -> dict[str, Any]:
    trigger = plan.trigger
    if trigger.conditions:
        partial_legs: list[dict[str, Any]] = []
        for idx, leg in enumerate(trigger.conditions):
            result = _evaluate_single_trigger(leg, observation)
            result["leg_index"] = idx
            result["description"] = leg.description
            if result["met"]:
                return {
                    "met": True,
                    "partial": False,
                    "matched_leg": result,
                    "reasons": [f"trigger leg {idx} met"],
                    "legs": [result],
                }
            if result["price_met"]:
                partial_legs.append(result)
        return {
            "met": False,
            "partial": bool(partial_legs),
            "matched_leg": partial_legs[0] if partial_legs else None,
            "reasons": ["price trigger met but confirmation missing"] if partial_legs else ["trigger not met"],
            "legs": partial_legs,
        }
    result = _evaluate_single_trigger(trigger, observation)
    return {
        "met": result["met"],
        "partial": result["price_met"] and not result["met"],
        "matched_leg": result if result["met"] or result["price_met"] else None,
        "reasons": result["reasons"] if result["reasons"] else (["trigger met"] if result["met"] else ["trigger not met"]),
        "legs": [result],
    }


def _evaluate_single_trigger(trigger, observation: MarketObservation) -> dict[str, Any]:
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
    reasons: list[str] = []
    if not price_ok:
        reasons.append("price trigger not met")
        return {"met": False, "price_met": False, "reasons": reasons}
    if trigger.volume_min_ratio is not None and (
        observation.volume_ratio is None or observation.volume_ratio < trigger.volume_min_ratio
    ):
        reasons.append("volume confirmation missing")
    if trigger.rsi_min is not None and (observation.rsi_14 is None or observation.rsi_14 < trigger.rsi_min):
        reasons.append("rsi_min confirmation missing")
    if trigger.rsi_max is not None and (observation.rsi_14 is None or observation.rsi_14 > trigger.rsi_max):
        reasons.append("rsi_max confirmation missing")
    if trigger.require_price_above_sma_50 and (
        observation.sma_50 is None or observation.price <= observation.sma_50
    ):
        reasons.append("sma_50 confirmation missing")
    if trigger.require_price_above_sma_200 and (
        observation.sma_200 is None or observation.price <= observation.sma_200
    ):
        reasons.append("sma_200 confirmation missing")
    if trigger.require_reclaim_sma_50 and (
        observation.sma_50 is None or observation.price <= observation.sma_50
    ):
        reasons.append("reclaim_sma_50 confirmation missing")
    if trigger.require_reclaim_sma_200 and (
        observation.sma_200 is None or observation.price <= observation.sma_200
    ):
        reasons.append("reclaim_sma_200 confirmation missing")
    return {"met": not reasons, "price_met": True, "reasons": reasons}

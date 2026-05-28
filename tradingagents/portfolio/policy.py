from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PositionSizeResult:
    entry_price: float
    invalidation_price: float
    invalidation_distance_pct: float
    allowed_risk_pct: float
    raw_notional_pct: float
    clipped_notional_pct: float
    applied_caps: tuple[str, ...]


def _float_config(config: dict[str, Any] | None, key: str, default: float) -> float:
    try:
        return float((config or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _int_config(config: dict[str, Any] | None, key: str, default: int) -> int:
    try:
        return int((config or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _range_config(config: dict[str, Any] | None, key: str, default: tuple[float, float]) -> tuple[float, float]:
    raw = (config or {}).get(key)
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            return float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return default
    return default


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _money_to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"-?\$?([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def get_portfolio_policy(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    style = str(cfg.get("portfolio_style") or "trend_concentrated").strip().lower()
    target_ticket_count = _int_config(cfg, "target_ticket_count", 5)
    return {
        "style": style,
        "target_ticket_count": target_ticket_count,
        "theme_concentration_enabled": bool(cfg.get("theme_concentration_enabled", True)),
        "max_single_name_notional_pct": _float_config(cfg, "max_single_name_notional_pct", 0.30),
        "max_theme_notional_pct": _float_config(cfg, "max_theme_notional_pct", 0.70),
        "max_single_name_risk_pct": _float_config(cfg, "max_single_name_risk_pct", 0.025),
        "max_theme_risk_pct": _float_config(cfg, "max_theme_risk_pct", 0.08),
        "max_account_open_risk_pct": _float_config(cfg, "max_account_open_risk_pct", 0.12),
        "leader_notional_range_pct": _range_config(cfg, "leader_notional_range_pct", (0.20, 0.30)),
        "core_notional_range_pct": _range_config(cfg, "core_notional_range_pct", (0.10, 0.20)),
        "starter_notional_range_pct": _range_config(cfg, "starter_notional_range_pct", (0.05, 0.10)),
    }


def get_ticker_theme(ticker: str, config: dict[str, Any] | None = None) -> str:
    symbol = str(ticker or "").upper().replace("/", "")
    theme_map = (config or {}).get("theme_map") or {}
    normalized = {str(k).upper().replace("/", ""): str(v) for k, v in theme_map.items()}
    return normalized.get(symbol, "unmapped")


def compute_position_size(
    *,
    entry_price: float,
    invalidation_price: float,
    allowed_risk_pct: float,
    max_single_name_notional_pct: float | None = None,
    theme_remaining_notional_pct: float | None = None,
) -> PositionSizeResult:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if invalidation_price <= 0:
        raise ValueError("invalidation_price must be positive")
    if allowed_risk_pct < 0:
        raise ValueError("allowed_risk_pct must be non-negative")

    invalidation_distance_pct = abs(entry_price - invalidation_price) / entry_price
    if invalidation_distance_pct == 0:
        raise ValueError("entry_price and invalidation_price must differ")

    raw_notional_pct = allowed_risk_pct / invalidation_distance_pct
    clipped_notional_pct = raw_notional_pct
    applied_caps: list[str] = []

    if max_single_name_notional_pct is not None and clipped_notional_pct > max_single_name_notional_pct:
        clipped_notional_pct = max_single_name_notional_pct
        applied_caps.append("single_name_notional_cap")

    if theme_remaining_notional_pct is not None and clipped_notional_pct > theme_remaining_notional_pct:
        clipped_notional_pct = max(theme_remaining_notional_pct, 0.0)
        applied_caps.append("theme_remaining_notional_cap")

    return PositionSizeResult(
        entry_price=entry_price,
        invalidation_price=invalidation_price,
        invalidation_distance_pct=invalidation_distance_pct,
        allowed_risk_pct=allowed_risk_pct,
        raw_notional_pct=raw_notional_pct,
        clipped_notional_pct=clipped_notional_pct,
        applied_caps=tuple(applied_caps),
    )


def build_portfolio_policy_context(config: dict[str, Any] | None = None) -> str:
    policy = get_portfolio_policy(config)
    starter = policy["starter_notional_range_pct"]
    core = policy["core_notional_range_pct"]
    leader = policy["leader_notional_range_pct"]
    if policy["style"] == "trend_concentrated":
        return "\n".join(
            [
                "Portfolio Policy: TREND_CONCENTRATED.",
                f"- Target basket size: {policy['target_ticket_count']} tickets, not an equal-weight 10-ticket diversified book.",
                "- Concentration is allowed when trend, relative strength, catalyst durability, and invalidation are aligned.",
                "- Prefer leader concentration over equal-weighting weaker same-theme names; add to winners and rotate out laggards.",
                f"- Starter notional range: {_pct(starter[0])}-{_pct(starter[1])} NAV.",
                f"- Core notional range: {_pct(core[0])}-{_pct(core[1])} NAV.",
                f"- Leader notional range: {_pct(leader[0])}-{_pct(leader[1])} NAV.",
                f"- Single-name cap: {_pct(policy['max_single_name_notional_pct'])} NAV notional and {_pct(policy['max_single_name_risk_pct'])} NAV risk-to-invalidation.",
                f"- Theme cap: {_pct(policy['max_theme_notional_pct'])} NAV notional and {_pct(policy['max_theme_risk_pct'])} NAV theme risk.",
                f"- Account open-risk cap: {_pct(policy['max_account_open_risk_pct'])} NAV. Keep >3.0% NAV single-name risk rare and explicit.",
            ]
        )
    return "\n".join(
        [
            "Portfolio Policy: DIVERSIFIED.",
            f"- Target basket size: {policy['target_ticket_count']} tickets.",
            "- Keep sizing balanced unless account context and relative strength justify concentration.",
            f"- Single-name cap: {_pct(policy['max_single_name_notional_pct'])} NAV notional and {_pct(policy['max_single_name_risk_pct'])} NAV risk-to-invalidation.",
        ]
    )


def build_sizing_guidance_context(config: dict[str, Any] | None = None) -> str:
    policy = get_portfolio_policy(config)
    return "\n".join(
        [
            "Deterministic sizing rule to apply before recommending exposure:",
            "- risk_to_invalidation_pct = abs(entry_price - invalidation_price) / entry_price.",
            "- notional_exposure_pct = allowed_risk_pct / risk_to_invalidation_pct.",
            "- Clip notional_exposure_pct by single-name cap, theme remaining capacity, liquidity/event risk, and correlation risk.",
            f"- Current caps: single-name {_pct(policy['max_single_name_notional_pct'])} NAV notional / {_pct(policy['max_single_name_risk_pct'])} NAV risk; theme {_pct(policy['max_theme_notional_pct'])} NAV notional / {_pct(policy['max_theme_risk_pct'])} NAV risk.",
            "- If the invalidation distance is too wide for an actionable size, output HOLD with a trigger instead of a token BUY.",
        ]
    )


def build_theme_basket_context(
    ticker: str,
    positions_data: list[dict[str, Any]] | None,
    account_info: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> str:
    policy = get_portfolio_policy(config)
    theme = get_ticker_theme(ticker, config)
    equity = _money_to_float((account_info or {}).get("equity")) or 0.0
    positions = positions_data or []
    theme_positions: list[tuple[str, float, float | None]] = []
    total_theme_value = 0.0

    for pos in positions:
        symbol = str(pos.get("Symbol", "")).upper().replace("/", "")
        same_theme = get_ticker_theme(symbol, config) == theme
        if theme == "unmapped":
            same_theme = symbol == str(ticker or "").upper().replace("/", "")
        if not same_theme:
            continue
        market_value = _money_to_float(pos.get("Market Value"))
        if market_value is None:
            continue
        total_theme_value += market_value
        weight = market_value / equity if equity > 0 else None
        theme_positions.append((symbol, market_value, weight))

    theme_exposure_pct = total_theme_value / equity if equity > 0 else 0.0
    remaining_theme_pct = max(policy["max_theme_notional_pct"] - theme_exposure_pct, 0.0)
    lines = [
        f"Theme Basket Context for {str(ticker).upper()}:",
        f"- Theme: {theme}.",
        f"- Theme concentration enabled: {policy['theme_concentration_enabled']}.",
        f"- Current theme exposure: {_pct(theme_exposure_pct)} NAV; remaining theme capacity: {_pct(remaining_theme_pct)} NAV.",
        f"- Theme notional cap: {_pct(policy['max_theme_notional_pct'])} NAV; theme risk cap: {_pct(policy['max_theme_risk_pct'])} NAV.",
    ]
    if theme_positions:
        formatted = ", ".join(
            f"{symbol} ${value:,.0f}" + (f" ({_pct(weight)})" if weight is not None else "")
            for symbol, value, weight in theme_positions
        )
        lines.append(f"- Current same-theme positions: {formatted}.")
    else:
        lines.append("- Current same-theme positions: none detected from Alpaca positions.")
    lines.extend(
        [
            "- Treat same-theme tickers as correlated theme risk, not independent bets.",
            "- If adding this ticker would exceed theme capacity, prefer replacing a weaker same-theme holding or wait.",
            "- If this ticker is the relative-strength leader, concentration is acceptable inside the caps; if it is a laggard, require a replacement rationale.",
        ]
    )
    return "\n".join(lines)

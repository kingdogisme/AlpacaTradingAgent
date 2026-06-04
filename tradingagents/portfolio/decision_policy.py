from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .policy import compute_position_size, get_portfolio_policy


DEFAULT_FACTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "swing": {
        "technical": 0.55,
        "news_social_catalyst": 0.20,
        "macro": 0.10,
        "fundamentals_valuation": 0.10,
        "portfolio_risk": 0.05,
    },
    "position": {
        "trend_relative_strength": 0.35,
        "catalyst_news_social": 0.25,
        "fundamentals": 0.15,
        "macro_liquidity": 0.15,
        "valuation": 0.10,
    },
    "trend": {
        "valuation": 0.30,
        "fundamentals": 0.25,
        "trend_regime": 0.20,
        "macro_liquidity": 0.15,
        "sentiment_news": 0.10,
    },
}

DEFAULT_GATE_THRESHOLDS: dict[str, dict[str, float]] = {
    "swing": {"min_weighted_score": 0.58, "min_technical_score": 0.50},
    "position": {"min_weighted_score": 0.60, "min_trend_confirmations": 2},
    "trend": {"min_weighted_score": 0.62, "max_valuation_score_without_support": 0.35},
}

DEFAULT_RISK_BUDGET_LADDER: dict[str, float] = {
    "blocked": 0.0,
    "weak_min": 0.005,
    "weak_max": 0.010,
    "valid_starter_min": 0.010,
    "valid_starter_max": 0.015,
    "confirmed_leader_min": 0.015,
    "confirmed_leader_max": 0.025,
}

DEFAULT_CROWDING_THRESHOLDS: dict[str, float] = {
    "price_vs_50d_high": 0.20,
    "price_vs_200d_high": 0.45,
    "drawdown_52w_tight": -0.05,
    "return_6m_high": 0.50,
    "volume_attention_ratio": 2.0,
    "bullish_social_ratio": 0.70,
    "mention_zscore": 2.0,
    "call_put_oi_ratio": 2.5,
    "iv_percentile": 80.0,
    "same_theme_notional": 0.60,
    "same_theme_risk": 0.07,
}

DEFAULT_MOMENTUM_CRASH_THRESHOLDS: dict[str, float] = {
    "benchmark_63d_return": -0.10,
    "benchmark_126d_return": -0.15,
    "benchmark_drawdown": -0.12,
    "benchmark_realized_vol_21d_percentile": 80.0,
    "benchmark_5d_rebound": 0.04,
    "benchmark_21d_rebound": 0.08,
    "high_momentum_relative_strength": 0.15,
    "high_momentum_6m_return": 0.40,
}

DEFAULT_RISK_OVERLAY_MULTIPLIERS: dict[str, float] = {
    "low": 1.0,
    "medium": 0.75,
    "high": 0.50,
    "extreme": 0.25,
    "momentum_crash": 0.50,
}

DEFAULT_SOFT_GATE_MULTIPLIERS: dict[str, float] = {
    "weighted_score": 0.75,
    "technical": 0.65,
    "trend_theme": 0.70,
    "valuation_fundamentals": 0.70,
}


@dataclass(frozen=True)
class HorizonFactorPolicy:
    horizon: str
    weights: dict[str, float]
    gate_thresholds: dict[str, float]
    risk_budget_ladder: dict[str, float]


@dataclass(frozen=True)
class FactorScore:
    name: str
    score: float
    weight: float
    contribution: float
    evidence: str = ""


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str
    severity: str = "hard"


@dataclass(frozen=True)
class CrowdingResult:
    level: str
    triggered_count: int
    triggered_conditions: tuple[str, ...]
    risk_multiplier: float
    blocked: bool


@dataclass(frozen=True)
class MomentumCrashResult:
    state: bool
    market_panic: bool
    high_vol: bool
    rebound: bool
    high_momentum_target: bool
    risk_multiplier: float
    blocked: bool
    reset_conditions: str = "Reset requires volatility cooling, relative strength holding, and price reclaiming 21D/50D with volume confirmation."


@dataclass(frozen=True)
class RiskOverlayResult:
    crowding: CrowdingResult
    momentum_crash: MomentumCrashResult
    risk_multiplier: float
    blocked_reason: str = ""


@dataclass(frozen=True)
class DecisionPolicyResult:
    horizon: str
    weighted_score: float
    factor_scores: tuple[FactorScore, ...]
    gate_results: tuple[GateResult, ...]
    risk_bucket: str
    allowed_risk_pct: float
    base_allowed_risk_pct: float
    recommended_action: str
    sizing_calculation: str
    risk_overlay: RiskOverlayResult
    soft_gate_multiplier: float = 1.0
    validator_note: str = ""

    @property
    def gate_passed(self) -> bool:
        return all(gate.passed for gate in self.gate_results)

    @property
    def hard_gate_passed(self) -> bool:
        return all(gate.passed for gate in self.gate_results if gate.severity == "hard")


def _horizon_key(horizon: str | None) -> str:
    key = str(horizon or "position").strip().lower()
    return key if key in DEFAULT_FACTOR_WEIGHTS else "position"


def _config_map(config: dict[str, Any] | None, key: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = (config or {}).get(key)
    if isinstance(raw, dict):
        merged = {k: dict(v) for k, v in default.items()}
        for map_key, value in raw.items():
            merged[str(map_key)] = dict(value) if isinstance(value, dict) else value
        return merged
    return default


def _float_config(config: dict[str, Any] | None, key: str, default: float) -> float:
    try:
        return float((config or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _bool_config(config: dict[str, Any] | None, key: str, default: bool) -> bool:
    raw = (config or {}).get(key, default)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _flat_config_map(config: dict[str, Any] | None, key: str, default: dict[str, float]) -> dict[str, float]:
    merged = dict(default)
    raw = (config or {}).get(key)
    if isinstance(raw, dict):
        for map_key, value in raw.items():
            try:
                merged[str(map_key)] = float(value)
            except (TypeError, ValueError):
                continue
    return merged


def get_horizon_factor_policy(config: dict[str, Any] | None = None, horizon: str | None = None) -> HorizonFactorPolicy:
    key = _horizon_key(horizon or (config or {}).get("trading_horizon"))
    weights_by_horizon = _config_map(config, "horizon_factor_weights", DEFAULT_FACTOR_WEIGHTS)
    thresholds_by_horizon = _config_map(config, "horizon_gate_thresholds", DEFAULT_GATE_THRESHOLDS)
    risk_ladder = dict(DEFAULT_RISK_BUDGET_LADDER)
    risk_ladder.update((config or {}).get("risk_budget_ladder") or {})
    return HorizonFactorPolicy(
        horizon=key,
        weights={str(k): float(v) for k, v in dict(weights_by_horizon[key]).items()},
        gate_thresholds={str(k): float(v) for k, v in dict(thresholds_by_horizon[key]).items()},
        risk_budget_ladder={str(k): float(v) for k, v in risk_ladder.items()},
    )


def build_decision_policy_context(config: dict[str, Any] | None = None, horizon: str | None = None) -> str:
    policy = get_horizon_factor_policy(config, horizon)
    weights = ", ".join(f"{name} {_pct(weight)}" for name, weight in policy.weights.items())
    ladder = policy.risk_budget_ladder
    if policy.horizon == "swing":
        gate = "Hard Gates: data quality, actionability, invalidation, and risk-to-invalidation. Soft Gates: weighted score and technical confirmation adjust size/confidence instead of vetoing by default."
    elif policy.horizon == "position":
        gate = "Hard Gates: data quality, actionability, invalidation, and risk-to-invalidation. Soft Gates: weighted score and trend/theme confirmations adjust size/confidence instead of vetoing by default."
    else:
        gate = "Hard Gates: data quality, actionability, invalidation, and risk-to-invalidation. Soft Gates: weighted score and valuation/fundamental support adjust size/confidence instead of vetoing by default."
    return "\n".join(
        [
            f"Decision Policy: deterministic {policy.horizon} methodology.",
            f"Factor Weights: {weights}.",
            "Academic Countercheck: momentum works over intermediate horizons, but value/fundamental quality, crowding, and momentum-crash states must constrain sizing.",
            gate,
            "Crowding Gate: price extension, abnormal volume/attention, social/options crowding, and same-theme exposure reduce risk by default; hard block only when configured.",
            "Momentum Crash Gate: after market panic plus high volatility plus rebound, high-momentum extended names receive reduced risk by default; hard block only when configured.",
            "Sizing Calculation: choose allowed_risk_pct from gate quality before notional sizing.",
            (
                "Risk Budget Ladder: blocked "
                f"{_pct(ladder['blocked'])}; weak {_pct(ladder['weak_min'])}-{_pct(ladder['weak_max'])}; "
                f"valid starter {_pct(ladder['valid_starter_min'])}-{_pct(ladder['valid_starter_max'])}; "
                f"confirmed leader {_pct(ladder['confirmed_leader_min'])}-{_pct(ladder['confirmed_leader_max'])}."
            ),
            "Required output fields: Factor Scores, Gate Checks, Sizing Calculation, User Recommendation, Alpaca Execution Action.",
        ]
    )


def evaluate_decision_policy(
    *,
    config: dict[str, Any] | None,
    horizon: str,
    proposed_action: str,
    factor_scores: dict[str, float] | None = None,
    evidence_text: str = "",
    overlay_inputs: dict[str, Any] | None = None,
    entry_price: float | None = None,
    invalidation_price: float | None = None,
    theme_remaining_notional_pct: float | None = None,
) -> DecisionPolicyResult:
    policy = get_horizon_factor_policy(config, horizon)
    scores = _normalize_factor_scores(policy, factor_scores or _infer_factor_scores(policy.horizon, evidence_text))
    weighted_score = round(sum(item.contribution for item in scores), 3)
    gate_results = _evaluate_gates(policy, scores, evidence_text, entry_price, invalidation_price)
    dynamic_soft_gates = _bool_config(config, "decision_policy_dynamic_soft_gates_enabled", True)
    hard_gate_passed = all(gate.passed for gate in gate_results if gate.severity == "hard")
    effective_gate_passed = hard_gate_passed if dynamic_soft_gates else all(gate.passed for gate in gate_results)
    risk_bucket, base_allowed_risk_pct = _risk_budget_for(policy, weighted_score, effective_gate_passed)
    soft_gate_multiplier = _soft_gate_multiplier(config, gate_results) if dynamic_soft_gates else 1.0
    risk_overlay = evaluate_risk_overlays(
        config=config,
        horizon=policy.horizon,
        weighted_score=weighted_score,
        evidence_text=evidence_text,
        overlay_inputs=overlay_inputs,
        theme_remaining_notional_pct=theme_remaining_notional_pct,
    )
    allowed_risk_pct = round(base_allowed_risk_pct * soft_gate_multiplier * risk_overlay.risk_multiplier, 6)
    sizing = _sizing_text(
        config=config,
        entry_price=entry_price,
        invalidation_price=invalidation_price,
        allowed_risk_pct=allowed_risk_pct,
        theme_remaining_notional_pct=theme_remaining_notional_pct,
    )
    recommended_action = str(proposed_action or "HOLD").upper()
    note = ""
    if recommended_action in {"BUY", "LONG"} and (not effective_gate_passed or risk_overlay.blocked_reason):
        recommended_action = "NEUTRAL" if recommended_action == "LONG" else "HOLD"
        failed = ", ".join(
            gate.name for gate in gate_results if not gate.passed and (not dynamic_soft_gates or gate.severity == "hard")
        )
        if risk_overlay.blocked_reason:
            note = f"decision policy overlay blocked BUY ({risk_overlay.blocked_reason}); action downgraded"
        else:
            note = f"decision policy gate failed ({failed}); action downgraded"
    min_notional = _float_config(config, "minimum_executable_notional_pct", 0.02)
    if recommended_action in {"BUY", "LONG"} and "notional_exposure_pct=" in sizing:
        notional = _extract_pct_decimal(sizing, "notional_exposure_pct")
        if notional is not None and notional < min_notional:
            recommended_action = "NEUTRAL" if recommended_action == "LONG" else "HOLD"
            note = f"decision policy sizing below minimum executable notional {_pct(min_notional)}; action downgraded"

    return DecisionPolicyResult(
        horizon=policy.horizon,
        weighted_score=weighted_score,
        factor_scores=tuple(scores),
        gate_results=tuple(gate_results),
        risk_bucket=risk_bucket,
        allowed_risk_pct=allowed_risk_pct,
        base_allowed_risk_pct=base_allowed_risk_pct,
        recommended_action=recommended_action,
        sizing_calculation=sizing,
        risk_overlay=risk_overlay,
        soft_gate_multiplier=soft_gate_multiplier,
        validator_note=note,
    )


def evaluate_risk_overlays(
    *,
    config: dict[str, Any] | None,
    horizon: str,
    weighted_score: float,
    evidence_text: str = "",
    overlay_inputs: dict[str, Any] | None = None,
    theme_remaining_notional_pct: float | None = None,
) -> RiskOverlayResult:
    inputs = _overlay_inputs_from_text(evidence_text)
    inputs.update({k: v for k, v in (overlay_inputs or {}).items() if v is not None})
    crowding = _evaluate_crowding(config, inputs, theme_remaining_notional_pct)
    momentum = _evaluate_momentum_crash(config, inputs)

    multiplier = 1.0
    if _bool_config(config, "crowding_gate_enabled", True):
        multiplier = min(multiplier, crowding.risk_multiplier)
    if _bool_config(config, "momentum_crash_gate_enabled", True) and momentum.state and momentum.high_momentum_target:
        multiplier = min(multiplier, momentum.risk_multiplier)

    blocked: list[str] = []
    if (
        _bool_config(config, "crowding_gate_enabled", True)
        and _bool_config(config, "crowding_extreme_blocks", False)
        and crowding.blocked
    ):
        blocked.append("crowding_gate=extreme")
    if (
        _bool_config(config, "momentum_crash_gate_enabled", True)
        and _bool_config(config, "momentum_crash_blocks", False)
        and momentum.blocked
        and horizon in {"position", "trend"}
        and weighted_score < 0.76
    ):
        blocked.append("momentum_crash_gate=blocked")

    return RiskOverlayResult(
        crowding=crowding,
        momentum_crash=momentum,
        risk_multiplier=round(multiplier, 3),
        blocked_reason=", ".join(blocked),
    )


def render_decision_policy_result(result: DecisionPolicyResult) -> str:
    factors = "; ".join(
        f"{item.name}={item.score:.2f} x {_pct(item.weight)} -> {item.contribution:.3f}"
        for item in result.factor_scores
    )
    gates = "; ".join(
        f"{gate.name}={'PASS' if gate.passed else 'FAIL'}[{gate.severity}] ({gate.reason})" for gate in result.gate_results
    )
    return "\n".join(
        [
            f"周期: {result.horizon}",
            f"因子分数: weighted_score={result.weighted_score:.3f}; {factors}",
            f"Gate 检查: {gates}",
            (
                "Academic Countercheck: momentum/value/fundamental-quality evidence checked; "
                f"Crowding Gate={result.risk_overlay.crowding.level}; "
                f"Momentum Crash Gate={'ON' if result.risk_overlay.momentum_crash.state else 'OFF'}"
            ),
            (
                f"Sizing 计算: risk_bucket={result.risk_bucket}; "
                f"base_allowed_risk_pct={_pct(result.base_allowed_risk_pct)}; "
                f"soft_gate_multiplier={result.soft_gate_multiplier:.2f}; "
                f"risk_multiplier={result.risk_overlay.risk_multiplier:.2f}; "
                f"allowed_risk_pct={_pct(result.allowed_risk_pct)}; {result.sizing_calculation}"
            ),
            f"解除条件: {result.risk_overlay.momentum_crash.reset_conditions}",
        ]
    )


def _normalize_factor_scores(policy: HorizonFactorPolicy, raw_scores: dict[str, float]) -> list[FactorScore]:
    scores: list[FactorScore] = []
    for name, weight in policy.weights.items():
        score = _clamp(float(raw_scores.get(name, 0.5)), 0.0, 1.0)
        scores.append(FactorScore(name=name, score=score, weight=weight, contribution=round(score * weight, 3)))
    return scores


def _evaluate_gates(
    policy: HorizonFactorPolicy,
    scores: list[FactorScore],
    evidence_text: str,
    entry_price: float | None,
    invalidation_price: float | None,
) -> list[GateResult]:
    score_map = {item.name: item.score for item in scores}
    text = str(evidence_text or "").lower()
    weighted = sum(item.contribution for item in scores)
    gates = [
        GateResult("data_quality", "data error" not in text and "unavailable" not in text, "usable evidence required"),
        GateResult("actionability", not _contains_future_only_trigger(text), "current setup must be actionable"),
        GateResult("invalidation", _has_invalidation(text) or bool(invalidation_price), "explicit invalidation required"),
        GateResult(
            "risk_to_invalidation",
            bool(entry_price and invalidation_price and entry_price > 0 and invalidation_price > 0 and entry_price != invalidation_price)
            or "risk-to-invalidation" in text.lower(),
            "risk-to-invalidation must be calculable",
        ),
        GateResult(
            "weighted_score",
            weighted >= policy.gate_thresholds.get("min_weighted_score", 0.60),
            f"weighted score {weighted:.3f} must meet threshold",
            "soft",
        ),
    ]
    if policy.horizon == "swing":
        technical = score_map.get("technical", 0.5)
        gates.append(
            GateResult(
                "technical",
                technical >= policy.gate_thresholds.get("min_technical_score", 0.5) and "technical bearish" not in text,
                "technical confirmation must not be bearish",
                "soft",
            )
        )
    elif policy.horizon == "position":
        confirmations = _position_confirmations(score_map, text)
        gates.append(
            GateResult(
                "trend_theme",
                confirmations >= int(policy.gate_thresholds.get("min_trend_confirmations", 2)),
                f"{confirmations} trend/theme confirmations detected",
                "soft",
            )
        )
    elif policy.horizon == "trend":
        valuation = score_map.get("valuation", 0.5)
        fundamentals = score_map.get("fundamentals", 0.5)
        extended = "extended" in text or "趋势延伸" in text or "估值过高" in text or "overvalu" in text
        gates.append(
            GateResult(
                "valuation_fundamentals",
                not (valuation <= policy.gate_thresholds.get("max_valuation_score_without_support", 0.35) and fundamentals < 0.65 and extended),
                "high valuation requires fundamental support",
                "soft",
            )
        )
    return gates


def _risk_budget_for(policy: HorizonFactorPolicy, weighted_score: float, gate_passed: bool) -> tuple[str, float]:
    ladder = policy.risk_budget_ladder
    if not gate_passed:
        return "blocked", ladder["blocked"]
    quality_floor = policy.gate_thresholds.get("min_weighted_score", 0.60) * 0.75
    if weighted_score < quality_floor:
        return "blocked", ladder["blocked"]
    if weighted_score >= 0.76:
        return "confirmed_leader", ladder["confirmed_leader_max"]
    if weighted_score >= 0.64:
        return "valid_starter", ladder["valid_starter_max"]
    return "weak", ladder["weak_max"]


def _soft_gate_multiplier(config: dict[str, Any] | None, gates: list[GateResult]) -> float:
    multipliers = _flat_config_map(config, "soft_gate_multipliers", DEFAULT_SOFT_GATE_MULTIPLIERS)
    value = 1.0
    for gate in gates:
        if gate.severity == "soft" and not gate.passed:
            value *= multipliers.get(gate.name, 0.75)
    return round(max(value, _float_config(config, "minimum_soft_gate_multiplier", 0.25)), 3)


def _sizing_text(
    *,
    config: dict[str, Any] | None,
    entry_price: float | None,
    invalidation_price: float | None,
    allowed_risk_pct: float,
    theme_remaining_notional_pct: float | None,
) -> str:
    if not entry_price or not invalidation_price or entry_price <= 0 or invalidation_price <= 0 or entry_price == invalidation_price:
        return "risk-to-invalidation unavailable; HOLD unless the LLM supplied a valid entry and invalidation."
    portfolio_policy = get_portfolio_policy(config)
    size = compute_position_size(
        entry_price=entry_price,
        invalidation_price=invalidation_price,
        allowed_risk_pct=allowed_risk_pct,
        max_single_name_notional_pct=portfolio_policy["max_single_name_notional_pct"],
        theme_remaining_notional_pct=theme_remaining_notional_pct,
    )
    caps = ",".join(size.applied_caps) if size.applied_caps else "none"
    return (
        f"risk_to_invalidation_pct={_pct(size.invalidation_distance_pct)}, "
        f"raw_notional_exposure_pct={_pct(size.raw_notional_pct)}, "
        f"notional_exposure_pct={_pct(size.clipped_notional_pct)}, caps={caps}"
    )


def _evaluate_crowding(
    config: dict[str, Any] | None,
    inputs: dict[str, Any],
    theme_remaining_notional_pct: float | None,
) -> CrowdingResult:
    thresholds = _flat_config_map(config, "crowding_thresholds", DEFAULT_CROWDING_THRESHOLDS)
    multipliers = _flat_config_map(config, "risk_overlay_multipliers", DEFAULT_RISK_OVERLAY_MULTIPLIERS)
    triggered: list[str] = []

    price_vs_50d = _input_float(inputs, "price_vs_50d")
    price_vs_200d = _input_float(inputs, "price_vs_200d")
    drawdown_52w = _input_float(inputs, "drawdown_from_52w_high")
    return_6m = _input_float(inputs, "return_6m")
    if (
        price_vs_50d is not None and price_vs_50d >= thresholds["price_vs_50d_high"]
    ) or (
        price_vs_200d is not None and price_vs_200d >= thresholds["price_vs_200d_high"]
    ) or (
        drawdown_52w is not None
        and return_6m is not None
        and drawdown_52w > thresholds["drawdown_52w_tight"]
        and return_6m >= thresholds["return_6m_high"]
    ):
        triggered.append("price_extension_high")

    volume_ratio = _input_float(inputs, "dollar_volume_20d_to_120d")
    if volume_ratio is not None and volume_ratio >= thresholds["volume_attention_ratio"]:
        triggered.append("volume_attention_high")

    bullish_social_ratio = _input_float(inputs, "bullish_social_ratio")
    mention_zscore = _input_float(inputs, "mention_zscore")
    if (
        bullish_social_ratio is not None
        and mention_zscore is not None
        and bullish_social_ratio >= thresholds["bullish_social_ratio"]
        and mention_zscore >= thresholds["mention_zscore"]
    ):
        triggered.append("sentiment_crowded")

    call_put_oi_ratio = _input_float(inputs, "call_put_oi_ratio")
    iv_percentile = _input_float(inputs, "iv_percentile")
    high_gex_pin = bool(inputs.get("spot_near_high_gex_pin", False))
    if (
        (call_put_oi_ratio is not None and call_put_oi_ratio >= thresholds["call_put_oi_ratio"])
        or (iv_percentile is not None and iv_percentile >= thresholds["iv_percentile"])
        or high_gex_pin
    ):
        triggered.append("options_crowded")

    same_theme_notional = _input_float(inputs, "same_theme_notional")
    same_theme_risk = _input_float(inputs, "same_theme_risk")
    if same_theme_notional is None and theme_remaining_notional_pct is not None:
        portfolio_policy = get_portfolio_policy(config)
        same_theme_notional = max(portfolio_policy["max_theme_notional_pct"] - theme_remaining_notional_pct, 0.0)
    if (
        same_theme_notional is not None and same_theme_notional >= thresholds["same_theme_notional"]
    ) or (
        same_theme_risk is not None and same_theme_risk >= thresholds["same_theme_risk"]
    ):
        triggered.append("theme_crowded")

    count = len(triggered)
    if count >= 4:
        level = "extreme"
    elif count == 3:
        level = "high"
    elif count == 2:
        level = "medium"
    else:
        level = "low"
    return CrowdingResult(
        level=level,
        triggered_count=count,
        triggered_conditions=tuple(triggered),
        risk_multiplier=multipliers.get(level, DEFAULT_RISK_OVERLAY_MULTIPLIERS[level]),
        blocked=level == "extreme",
    )


def _evaluate_momentum_crash(config: dict[str, Any] | None, inputs: dict[str, Any]) -> MomentumCrashResult:
    thresholds = _flat_config_map(config, "momentum_crash_thresholds", DEFAULT_MOMENTUM_CRASH_THRESHOLDS)
    multipliers = _flat_config_map(config, "risk_overlay_multipliers", DEFAULT_RISK_OVERLAY_MULTIPLIERS)
    bench_63d = _input_float(inputs, "benchmark_63d_return")
    bench_126d = _input_float(inputs, "benchmark_126d_return")
    bench_drawdown = _input_float(inputs, "benchmark_drawdown")
    bench_vol_pct = _input_float(inputs, "benchmark_realized_vol_21d_percentile")
    bench_5d = _input_float(inputs, "benchmark_5d_return")
    bench_21d = _input_float(inputs, "benchmark_21d_return")
    rel_3m = _input_float(inputs, "relative_3m")
    rel_6m = _input_float(inputs, "relative_6m")
    target_6m = _input_float(inputs, "return_6m")

    market_panic = any(
        condition
        for condition in (
            bench_63d is not None and bench_63d <= thresholds["benchmark_63d_return"],
            bench_126d is not None and bench_126d <= thresholds["benchmark_126d_return"],
            bench_drawdown is not None and bench_drawdown <= thresholds["benchmark_drawdown"],
        )
    )
    high_vol = bench_vol_pct is not None and bench_vol_pct >= thresholds["benchmark_realized_vol_21d_percentile"]
    rebound = any(
        condition
        for condition in (
            bench_5d is not None and bench_5d >= thresholds["benchmark_5d_rebound"],
            bench_21d is not None and bench_21d >= thresholds["benchmark_21d_rebound"],
        )
    )
    high_momentum_target = any(
        condition
        for condition in (
            rel_3m is not None and rel_3m >= thresholds["high_momentum_relative_strength"],
            rel_6m is not None and rel_6m >= thresholds["high_momentum_relative_strength"],
            target_6m is not None and target_6m >= thresholds["high_momentum_6m_return"],
        )
    )
    state = bool(market_panic and high_vol and rebound)
    return MomentumCrashResult(
        state=state,
        market_panic=market_panic,
        high_vol=high_vol,
        rebound=rebound,
        high_momentum_target=high_momentum_target,
        risk_multiplier=multipliers.get("momentum_crash", DEFAULT_RISK_OVERLAY_MULTIPLIERS["momentum_crash"]),
        blocked=bool(state and high_momentum_target),
    )


def _overlay_inputs_from_text(text: str) -> dict[str, Any]:
    lowered = str(text or "").lower()
    inputs: dict[str, Any] = {}
    patterns = {
        "benchmark_63d_return": r"benchmark[_\s-]*63d[_\s-]*return\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "benchmark_126d_return": r"benchmark[_\s-]*126d[_\s-]*return\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "benchmark_drawdown": r"benchmark[_\s-]*drawdown\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "benchmark_realized_vol_21d_percentile": r"(?:benchmark[_\s-]*)?realized[_\s-]*vol[_\s-]*21d[_\s-]*percentile\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "benchmark_5d_return": r"benchmark[_\s-]*5d[_\s-]*return\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "benchmark_21d_return": r"benchmark[_\s-]*21d[_\s-]*return\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "price_vs_50d": r"price[_\s-]*vs[_\s-]*50d\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "price_vs_200d": r"price[_\s-]*vs[_\s-]*200d\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "drawdown_from_52w_high": r"drawdown[_\s-]*from[_\s-]*52w[_\s-]*high\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "return_6m": r"return[_\s-]*6m\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "relative_3m": r"relative[_\s-]*3m\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "relative_6m": r"relative[_\s-]*6m\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "dollar_volume_20d_to_120d": r"(?:dollar[_\s-]*)?volume[_\s-]*20d[_\s-]*(?:/|to)[_\s-]*120d\s*[:=]\s*(-?\d+(?:\.\d+)?)x?",
        "bullish_social_ratio": r"bullish[_\s-]*social[_\s-]*ratio\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "mention_zscore": r"mention[_\s-]*z(?:score)?\s*[:=]\s*(-?\d+(?:\.\d+)?)",
        "call_put_oi_ratio": r"call[_\s-]*put[_\s-]*oi[_\s-]*ratio\s*[:=]\s*(-?\d+(?:\.\d+)?)",
        "iv_percentile": r"iv[_\s-]*percentile\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "same_theme_notional": r"same[_\s-]*theme[_\s-]*notional\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
        "same_theme_risk": r"same[_\s-]*theme[_\s-]*risk\s*[:=]\s*(-?\d+(?:\.\d+)?)%?",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, lowered)
        if match:
            value = float(match.group(1))
            if key != "dollar_volume_20d_to_120d" and abs(value) > 1.0:
                value = value / 100.0
            inputs[key] = value
    if "high-gex pin" in lowered or "near high gex" in lowered or "pin risk" in lowered:
        inputs["spot_near_high_gex_pin"] = True
    return inputs


def _input_float(inputs: dict[str, Any], key: str) -> float | None:
    value = inputs.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_factor_scores(horizon: str, text: str) -> dict[str, float]:
    lowered = str(text or "").lower()
    bullish = _count_terms(lowered, ("bullish", "outperform", "uptrend", "breakout", "higher highs", "growth", "beat", "上修", "强势"))
    bearish = _count_terms(lowered, ("bearish", "underperform", "downtrend", "breakdown", "overvalued", "expensive", "高估", "转弱"))
    base = _clamp(0.5 + (bullish - bearish) * 0.06, 0.15, 0.85)
    if horizon == "swing":
        technical = _clamp(base + (0.15 if "technical bearish" not in lowered and "bearish" not in lowered else -0.25), 0.0, 1.0)
        return {
            "technical": technical,
            "news_social_catalyst": base,
            "macro": _macro_score(lowered),
            "fundamentals_valuation": base,
            "portfolio_risk": 0.60,
        }
    if horizon == "position":
        return {
            "trend_relative_strength": _clamp(base + (0.10 if "relative strength" in lowered or "相对强" in lowered else 0.0), 0.0, 1.0),
            "catalyst_news_social": _clamp(base + (0.10 if "catalyst" in lowered or "催化" in lowered else 0.0), 0.0, 1.0),
            "fundamentals": base,
            "macro_liquidity": _macro_score(lowered),
            "valuation": _valuation_score(lowered),
        }
    return {
        "valuation": _valuation_score(lowered),
        "fundamentals": _clamp(base + (0.12 if "cash flow" in lowered or "profit" in lowered or "利润" in lowered else 0.0), 0.0, 1.0),
        "trend_regime": base,
        "macro_liquidity": _macro_score(lowered),
        "sentiment_news": base,
    }


def _valuation_score(text: str) -> float:
    if "overvalued" in text or "expensive" in text or "估值过高" in text or "高估" in text:
        return 0.25
    if "reasonable valuation" in text or "估值合理" in text or "undervalued" in text:
        return 0.75
    return 0.50


def _macro_score(text: str) -> float:
    if "tight liquidity" in text or "yield pressure" in text or "利率压力" in text or "流动性偏紧" in text:
        return 0.35
    if "supportive liquidity" in text or "easing" in text or "流动性宽松" in text:
        return 0.70
    return 0.50


def _position_confirmations(score_map: dict[str, float], text: str) -> int:
    confirmations = 0
    confirmations += int(score_map.get("trend_relative_strength", 0.0) >= 0.60)
    confirmations += int(score_map.get("catalyst_news_social", 0.0) >= 0.60)
    confirmations += int("higher high" in text or "breakout" in text or "相对强" in text or "趋势" in text)
    return confirmations


def _contains_future_only_trigger(text: str) -> bool:
    lowered = str(text or "").lower()
    if "current setup is actionable" in lowered or "actionable now" in lowered or "当前可执行" in lowered:
        return False
    return any(phrase in lowered for phrase in ("buy only if", "buy if", "wait for", "等待", "触发后", "future pullback", "future breakout"))


def _has_invalidation(text: str) -> bool:
    return "invalidation" in text or "stop" in text or "失效" in text or "止损" in text


def _extract_pct_decimal(text: str, key: str) -> float | None:
    match = re.search(rf"{re.escape(key)}=([0-9]+(?:\.[0-9]+)?)%", text)
    if not match:
        return None
    return float(match.group(1)) / 100.0


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

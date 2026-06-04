from __future__ import annotations

import pytest

from tradingagents.portfolio import (
    build_decision_policy_context,
    evaluate_decision_policy,
    evaluate_risk_overlays,
)


def test_swing_technical_bearish_blocks_buy(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="swing",
        proposed_action="BUY",
        factor_scores={
            "technical": 0.20,
            "news_social_catalyst": 0.75,
            "macro": 0.60,
            "fundamentals_valuation": 0.90,
            "portfolio_risk": 0.70,
        },
        evidence_text="technical bearish but valuation cheap. invalidation at 95. risk-to-invalidation defined.",
        entry_price=100,
        invalidation_price=95,
    )

    assert result.recommended_action == "BUY"
    assert not result.gate_passed
    assert result.hard_gate_passed
    assert result.soft_gate_multiplier < 1.0
    assert result.allowed_risk_pct > 0
    assert any(gate.name == "technical" and not gate.passed for gate in result.gate_results)


def test_hard_actionability_gate_still_blocks_buy(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="swing",
        proposed_action="BUY",
        factor_scores={
            "technical": 0.80,
            "news_social_catalyst": 0.75,
            "macro": 0.60,
            "fundamentals_valuation": 0.70,
            "portfolio_risk": 0.70,
        },
        evidence_text="wait for pullback or future breakout confirmation. invalidation at 95. risk-to-invalidation defined.",
        entry_price=100,
        invalidation_price=95,
    )

    assert result.recommended_action == "HOLD"
    assert not result.hard_gate_passed
    assert any(gate.name == "actionability" and not gate.passed for gate in result.gate_results)


def test_position_strong_theme_allows_expensive_starter_but_reduces_sizing(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.78,
            "catalyst_news_social": 0.72,
            "fundamentals": 0.60,
            "macro_liquidity": 0.55,
            "valuation": 0.30,
        },
        evidence_text="relative strength and catalyst durability with breakout trend. invalidation at 90.",
        entry_price=100,
        invalidation_price=90,
    )

    assert result.recommended_action == "BUY"
    assert result.gate_passed
    assert result.risk_bucket == "valid_starter"
    assert result.allowed_risk_pct == pytest.approx(0.015)


def test_trend_overvalued_without_fundamental_support_must_hold(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="trend",
        proposed_action="BUY",
        factor_scores={
            "valuation": 0.20,
            "fundamentals": 0.40,
            "trend_regime": 0.80,
            "macro_liquidity": 0.55,
            "sentiment_news": 0.65,
        },
        evidence_text="overvalued and extended trend. invalidation at 85. risk-to-invalidation defined.",
        entry_price=100,
        invalidation_price=85,
    )

    assert result.recommended_action == "BUY"
    assert result.hard_gate_passed
    assert result.soft_gate_multiplier < 1.0
    assert any(gate.name == "valuation_fundamentals" and not gate.passed for gate in result.gate_results)


def test_decision_policy_sizing_clips_by_single_name_and_theme_caps(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.90,
            "catalyst_news_social": 0.80,
            "fundamentals": 0.80,
            "macro_liquidity": 0.70,
            "valuation": 0.60,
        },
        evidence_text="relative strength catalyst breakout trend. invalidation at 95.",
        entry_price=100,
        invalidation_price=95,
        theme_remaining_notional_pct=0.20,
    )

    assert result.allowed_risk_pct == pytest.approx(0.025)
    assert "risk_to_invalidation_pct=5.0%" in result.sizing_calculation
    assert "notional_exposure_pct=20.0%" in result.sizing_calculation
    assert "theme_remaining_notional_cap" in result.sizing_calculation


def test_decision_policy_context_exposes_required_prompt_contract(isolated_config):
    context = build_decision_policy_context(isolated_config, "trend")

    assert "Factor Weights" in context
    assert "Gate Checks" in context
    assert "Sizing Calculation" in context
    assert "Crowding Gate" in context
    assert "Momentum Crash Gate" in context
    assert "Academic Countercheck" in context


def test_momentum_crash_state_detects_panic_high_vol_rebound(isolated_config):
    result = evaluate_risk_overlays(
        config=isolated_config,
        horizon="position",
        weighted_score=0.72,
        overlay_inputs={
            "benchmark_63d_return": -0.12,
            "benchmark_realized_vol_21d_percentile": 85,
            "benchmark_5d_return": 0.05,
            "relative_3m": 0.20,
        },
    )

    assert result.momentum_crash.state is True
    assert result.momentum_crash.blocked is True
    assert result.risk_multiplier == pytest.approx(0.5)


def test_momentum_crash_blocks_high_momentum_buy_when_not_confirmed_leader(isolated_config):
    isolated_config["momentum_crash_blocks"] = True
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.72,
            "catalyst_news_social": 0.68,
            "fundamentals": 0.62,
            "macro_liquidity": 0.50,
            "valuation": 0.45,
        },
        evidence_text="relative strength catalyst breakout trend. invalidation at 90. current setup is actionable.",
        overlay_inputs={
            "benchmark_63d_return": -0.12,
            "benchmark_realized_vol_21d_percentile": 85,
            "benchmark_5d_return": 0.05,
            "relative_3m": 0.20,
        },
        entry_price=100,
        invalidation_price=90,
    )

    assert result.recommended_action == "HOLD"
    assert "momentum_crash_gate=blocked" in result.risk_overlay.blocked_reason


def test_crowding_extreme_downgrades_buy_to_hold(isolated_config):
    isolated_config["crowding_extreme_blocks"] = True
    isolated_config["risk_overlay_multipliers"] = {**isolated_config["risk_overlay_multipliers"], "extreme": 0.0}
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.90,
            "catalyst_news_social": 0.86,
            "fundamentals": 0.78,
            "macro_liquidity": 0.66,
            "valuation": 0.58,
        },
        evidence_text="relative strength catalyst breakout trend. invalidation at 95. current setup is actionable.",
        overlay_inputs={
            "price_vs_50d": 0.25,
            "dollar_volume_20d_to_120d": 2.5,
            "bullish_social_ratio": 0.80,
            "mention_zscore": 2.5,
            "call_put_oi_ratio": 3.0,
        },
        entry_price=100,
        invalidation_price=95,
    )

    assert result.risk_overlay.crowding.level == "extreme"
    assert result.recommended_action == "HOLD"
    assert "crowding_gate=extreme" in result.risk_overlay.blocked_reason


def test_crowding_extreme_reduces_size_without_blocking_by_default(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.90,
            "catalyst_news_social": 0.86,
            "fundamentals": 0.78,
            "macro_liquidity": 0.66,
            "valuation": 0.58,
        },
        evidence_text="relative strength catalyst breakout trend. invalidation at 95. current setup is actionable.",
        overlay_inputs={
            "price_vs_50d": 0.25,
            "dollar_volume_20d_to_120d": 2.5,
            "bullish_social_ratio": 0.80,
            "mention_zscore": 2.5,
            "call_put_oi_ratio": 3.0,
        },
        entry_price=100,
        invalidation_price=95,
    )

    assert result.risk_overlay.crowding.level == "extreme"
    assert result.recommended_action == "BUY"
    assert result.risk_overlay.blocked_reason == ""
    assert result.allowed_risk_pct == pytest.approx(result.base_allowed_risk_pct * 0.25)


def test_crowding_high_reduces_risk_without_blocking_strong_setup(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.90,
            "catalyst_news_social": 0.86,
            "fundamentals": 0.80,
            "macro_liquidity": 0.70,
            "valuation": 0.60,
        },
        evidence_text="relative strength catalyst breakout trend. invalidation at 95. current setup is actionable.",
        overlay_inputs={
            "price_vs_50d": 0.25,
            "dollar_volume_20d_to_120d": 2.5,
            "call_put_oi_ratio": 3.0,
        },
        entry_price=100,
        invalidation_price=95,
    )

    assert result.recommended_action == "BUY"
    assert result.risk_overlay.crowding.level == "high"
    assert result.base_allowed_risk_pct == pytest.approx(0.025)
    assert result.allowed_risk_pct == pytest.approx(0.0125)


def test_theme_concentration_alone_is_not_extreme_when_theme_risk_within_cap(isolated_config):
    result = evaluate_decision_policy(
        config=isolated_config,
        horizon="position",
        proposed_action="BUY",
        factor_scores={
            "trend_relative_strength": 0.90,
            "catalyst_news_social": 0.80,
            "fundamentals": 0.78,
            "macro_liquidity": 0.66,
            "valuation": 0.58,
        },
        evidence_text="relative strength catalyst breakout trend. invalidation at 95. current setup is actionable.",
        overlay_inputs={"same_theme_notional": 0.65, "same_theme_risk": 0.06},
        entry_price=100,
        invalidation_price=95,
    )

    assert result.risk_overlay.crowding.level == "low"
    assert result.recommended_action == "BUY"

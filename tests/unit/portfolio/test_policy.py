from __future__ import annotations

import pytest

from tradingagents.portfolio import (
    build_portfolio_policy_context,
    build_theme_basket_context,
    compute_position_size,
    get_ticker_theme,
)


def test_compute_position_size_uses_risk_to_invalidation():
    result = compute_position_size(
        entry_price=310.0,
        invalidation_price=271.25,
        allowed_risk_pct=0.015,
        max_single_name_notional_pct=0.30,
    )

    assert result.invalidation_distance_pct == pytest.approx(0.125)
    assert result.raw_notional_pct == pytest.approx(0.12)
    assert result.clipped_notional_pct == pytest.approx(0.12)
    assert result.applied_caps == ()


def test_compute_position_size_clips_to_single_name_and_theme_caps():
    result = compute_position_size(
        entry_price=100.0,
        invalidation_price=95.0,
        allowed_risk_pct=0.025,
        max_single_name_notional_pct=0.30,
        theme_remaining_notional_pct=0.20,
    )

    assert result.raw_notional_pct == pytest.approx(0.50)
    assert result.clipped_notional_pct == pytest.approx(0.20)
    assert result.applied_caps == ("single_name_notional_cap", "theme_remaining_notional_cap")


def test_ticker_theme_uses_configured_theme_map(isolated_config):
    assert get_ticker_theme("BE", isolated_config) == "ai_power_infrastructure"
    assert get_ticker_theme("UNKNOWN", isolated_config) == "unmapped"


def test_portfolio_policy_context_describes_trend_concentration(isolated_config):
    context = build_portfolio_policy_context(isolated_config)

    assert "TREND_CONCENTRATED" in context
    assert "Target basket size: 5 tickets" in context
    assert "Prefer leader concentration" in context
    assert "Theme cap: 70.0% NAV notional" in context


def test_theme_basket_context_sums_same_theme_positions(isolated_config):
    positions = [
        {"Symbol": "BE", "Market Value": "$20,000.00"},
        {"Symbol": "VRT", "Market Value": "$15,000.00"},
        {"Symbol": "AAPL", "Market Value": "$10,000.00"},
    ]
    account = {"equity": 100000}

    context = build_theme_basket_context("BE", positions, account, isolated_config)

    assert "Theme: ai_power_infrastructure" in context
    assert "Current theme exposure: 35.0% NAV" in context
    assert "remaining theme capacity: 35.0% NAV" in context
    assert "BE $20,000 (20.0%)" in context
    assert "VRT $15,000 (15.0%)" in context
    assert "AAPL" not in context

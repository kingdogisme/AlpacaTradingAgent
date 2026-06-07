from __future__ import annotations

import ast
from pathlib import Path

from tradingagents.dataflows.data_quality import (
    build_quality_header,
    evaluate_tool_output,
    get_source_spec,
)


def test_evaluate_price_bars_marks_stale_critical_failure():
    result = evaluate_tool_output(
        "get_alpaca_data",
        {"symbol": "AAPL", "end_date": "2026-05-20"},
        "timestamp open high low close volume\n2026-04-01 1 2 1 1.5 1000",
        artifact_ref="tool_call:1",
    )

    assert result["source_id"] == "alpaca_bars"
    assert result["criticality"] == "critical"
    assert result["status"] == "fail"
    assert "stale_source" in result["flags"]
    assert result["artifact"]["raw_output_ref"] == "tool_call:1"


def test_quality_header_is_machine_readable():
    quality = evaluate_tool_output(
        "get_finnhub_news_recent",
        {"ticker": "AAPL", "curr_date": "2026-05-20"},
        "Source: Finnhub\nPublished: 2026-05-19\nAAPL launches product.",
        artifact_ref="tool_call:2",
    )

    header = build_quality_header(quality)

    assert header.startswith("[DATA_QUALITY]")
    assert "source_id: finnhub_news" in header
    assert "artifact_ref: tool_call:2" in header


def test_trend_brief_generated_at_counts_as_observed_date():
    result = evaluate_tool_output(
        "get_trend_brief",
        {"symbol": "AAPL", "curr_date": "2026-05-20"},
        '{"symbol":"AAPL","horizon":"trend","generated_at":"2026-05-20T13:00:00Z","timeframes":[]}',
        artifact_ref="tool_call:3",
    )

    assert result["status"] == "pass"
    assert result["observed_at"] == "2026-05-20"
    assert "missing_observed_timestamp" not in result["flags"]


def test_social_quality_uses_report_as_of_not_future_dates():
    result = evaluate_tool_output(
        "get_sellthenews_social_sentiment",
        {"ticker": "MSFT", "curr_date": "2026-06-04"},
        (
            "=== WSB Analysis: Daily Discussion Thread for June 04, 2026 ===\n"
            "Updated: 2026-06-04 09:21:23 ET\n"
            "Mentions include an unrelated historical date 2028-01-21."
        ),
        artifact_ref="tool_call:4",
    )

    assert result["status"] == "pass"
    assert result["observed_at"] == "2026-06-04"
    assert "future_observed_timestamp" not in result["flags"]


def test_fundamentals_quality_uses_as_of_not_future_metric_periods():
    result = evaluate_tool_output(
        "get_finnhub_company_fundamentals",
        {"ticker": "CRM", "curr_date": "2026-06-04"},
        (
            "## Finnhub Fundamentals for CRM as of 2026-06-04\n"
            "Annual salesPerShare: 2026-06-30: 43.4"
        ),
        artifact_ref="tool_call:5",
    )

    assert result["observed_at"] == "2026-06-04"
    assert "future_observed_timestamp" not in result["flags"]


def test_sec_quality_does_not_mark_stale_metric_note_unavailable():
    result = evaluate_tool_output(
        "get_sec_edgar_fundamentals",
        {"ticker": "RCAT", "curr_date": "2026-06-04"},
        (
            "## SEC EDGAR Official Fundamentals for RCAT as of 2026-06-04\n"
            "### Filing quality flags\n"
            "- preferred tag Revenues skipped because latest fact was stale; "
            "latest SEC cash fact 2021-07-31"
        ),
        artifact_ref="tool_call:6",
    )

    assert result["status"] == "pass"
    assert "source_unavailable" not in result["flags"]


def test_options_quality_warns_when_required_levels_missing():
    result = evaluate_tool_output(
        "get_sellthenews_options_data",
        {"ticker": "AVGO", "curr_date": "2026-05-20"},
        (
            "Spot Price: $1200\n"
            "Selected Expiration: 2026-05-22\n"
            "Gamma Flip: $1190\n"
            "Net GEX: 1000000\n"
        ),
        artifact_ref="tool_call:4",
    )

    assert result["status"] == "warn"
    assert result["completeness"] == "warn"
    assert "missing_required_options_levels" in result["flags"]


def test_all_toolkit_tools_have_source_spec():
    module = ast.parse(Path("tradingagents/agents/utils/agent_utils.py").read_text(encoding="utf-8"))
    toolkit = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Toolkit")
    tool_names = []
    for node in toolkit.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        has_tool_decorator = any(
            (isinstance(decorator, ast.Name) and decorator.id == "tool")
            or (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", None) == "tool")
            for decorator in node.decorator_list
        )
        if has_tool_decorator:
            tool_names.append(node.name)

    missing = [name for name in tool_names if get_source_spec(name).source_id == "unknown"]

    assert missing == []

from __future__ import annotations

from webui.components.data_quality_panel import render_data_quality_panel, summarize_tool_call_quality
from webui.components.tool_outputs_modal import format_tool_outputs_content


def _tool_call():
    return {
        "tool_name": "get_alpaca_data",
        "status": "degraded",
        "agent_type": "MARKET",
        "symbol": "AAPL",
        "inputs": {"symbol": "AAPL"},
        "output": "raw",
        "execution_time": "0.10s",
        "quality_details": {
            "data_quality": {
                "status": "fail",
                "source_id": "alpaca_bars",
                "provider": "Alpaca",
                "dataset_type": "price_bars",
                "flags": ["stale_source"],
                "observed_at": "2026-05-01",
                "criticality": "critical",
            }
        },
    }


def _quality_call(status, source_id, *, flags=None, fallback_from=None, criticality="medium"):
    return {
        "tool_name": f"tool_{source_id}",
        "status": "success" if status == "pass" else "degraded",
        "agent_type": "TEST",
        "symbol": "AAPL",
        "inputs": {"symbol": "AAPL"},
        "output": "raw",
        "execution_time": "0.01s",
        "quality_details": {
            "data_quality": {
                "status": status,
                "source_id": source_id,
                "provider": "Provider",
                "dataset_type": "news",
                "flags": flags or [],
                "observed_at": "2026-05-20",
                "fallback_from": fallback_from,
                "criticality": criticality,
            }
        },
    }


def test_summarize_tool_call_quality_counts_statuses():
    summary = summarize_tool_call_quality([_tool_call()])

    assert summary["counts"]["fail"] == 1
    assert summary["stale_sources"] == ["alpaca_bars"]
    assert summary["critical_failures"] == ["alpaca_bars"]


def test_summarize_tool_call_quality_tracks_all_statuses_and_fallbacks():
    calls = [
        _quality_call("pass", "direct_news"),
        _quality_call("warn", "finnhub_news", flags=["stale_source"]),
        _quality_call("fail", "alpaca_bars", flags=["stale_source"], criticality="critical"),
        _quality_call("unknown", "unregistered_tool_source", fallback_from="fallback_provider"),
    ]

    summary = summarize_tool_call_quality(calls)

    assert summary["counts"] == {"pass": 1, "warn": 1, "fail": 1, "unknown": 1}
    assert summary["stale_sources"] == ["alpaca_bars", "finnhub_news"]
    assert summary["fallback_sources"] == ["unregistered_tool_source"]
    assert summary["critical_failures"] == ["alpaca_bars"]


def test_render_data_quality_panel_returns_component():
    component = render_data_quality_panel([_tool_call()])

    assert component.__class__.__name__ == "Div"


def test_render_data_quality_panel_mentions_risk_categories():
    component = render_data_quality_panel(
        [
            _quality_call("fail", "alpaca_bars", flags=["stale_source"], criticality="critical"),
            _quality_call("warn", "finnhub_news", fallback_from="google_news"),
        ]
    )

    rendered = repr(component)

    assert "critical failures: alpaca_bars" in rendered
    assert "stale: alpaca_bars" in rendered
    assert "fallback: finnhub_news" in rendered


def test_tool_outputs_modal_includes_quality_fields():
    formatted = format_tool_outputs_content([_tool_call()], "market_report")

    assert "Data Quality" in formatted
    assert "alpaca_bars" in formatted
    assert "stale_source" in formatted

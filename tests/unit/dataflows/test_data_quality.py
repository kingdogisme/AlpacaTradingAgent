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

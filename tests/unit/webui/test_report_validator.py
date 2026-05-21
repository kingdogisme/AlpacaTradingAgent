from __future__ import annotations

from webui.utils.report_validator import (
    get_report_completion_status,
    is_report_complete,
    validate_reports_for_ui,
)
from webui.callbacks.report_callbacks import normalize_decision_markdown_sections
from webui.callbacks.report_callbacks import prepare_report_markdown, render_report_markdown


def test_report_completion_rejects_short_table_before_minimum_length():
    content = """
| Metric | Status |
|--------|--------|
| Trend | Bullish |
"""

    assert not is_report_complete(content, "market_report")


def test_report_completion_accepts_markdown_table_after_minimum_length():
    content = """
| Metric | Status | Evidence |
|--------|--------|----------|
| Trend | Bullish | Price action remains above the moving-average stack with improving breadth. |
| Volume | Confirming | Participation expanded enough to satisfy the report validator length gate. |
"""

    assert len(content.strip()) >= 100
    assert is_report_complete(content, "market_report")


def test_validate_reports_marks_missing_and_incomplete_content():
    reports = {
        "market_report": "too short",
        "news_report": None,
    }

    validated = validate_reports_for_ui(reports)
    status = get_report_completion_status(reports)

    assert "In Progress" in validated["market_report"]
    assert validated["news_report"].startswith("No News Report")
    assert status == {"market_report": "incomplete", "news_report": "missing"}


def test_decision_markdown_normalization_splits_inline_fields():
    content = (
        "**Action**: HOLD **Confidence**: medium "
        "**Risk Rationale**: Volatility is elevated. "
        "**Required Controls**: Keep stop discipline. "
        "FINAL TRANSACTION PROPOSAL: **HOLD**"
    )

    normalized = normalize_decision_markdown_sections(content)

    assert "### Action\nHOLD" in normalized
    assert "### Confidence\nmedium" in normalized
    assert "### Risk Rationale\nVolatility is elevated." in normalized
    assert "### Final Transaction Proposal\n\n**HOLD**" in normalized


def test_final_decision_markdown_normalization_supports_user_and_alpaca_sections():
    content = (
        "**操作**: BUY **信心**: medium "
        "**给用户的操作建议**: starter buy，等待回踩加仓。 "
        "**给 Alpaca 的直接动作**: BUY open starter 8% NAV。 "
        "FINAL TRANSACTION PROPOSAL: **BUY**"
    )

    normalized = prepare_report_markdown(content, "final_trade_decision")

    assert "### 操作\nBUY" in normalized
    assert "### 给用户的操作建议\nstarter buy，等待回踩加仓。" in normalized
    assert "### 给 Alpaca 的直接动作\nBUY open starter 8% NAV。" in normalized
    assert "### Final Transaction Proposal\n**BUY**" in normalized


def test_render_report_markdown_uses_dash_markdown_component():
    component = render_report_markdown(
        "**User Recommendation**: Starter buy.\nFINAL TRANSACTION PROPOSAL: **BUY**",
        report_type="final_trade_decision",
    )

    assert component.__class__.__name__ == "Markdown"
    assert component.dangerously_allow_html is False
    assert "### User Recommendation\nStarter buy." in component.children


def test_report_markdown_preserves_table_and_final_transaction_proposal():
    content = (
        "Summary Table | Metric | Value | | Trend | Bullish | "
        "**Action**: HOLD FINAL TRANSACTION PROPOSAL: **HOLD**"
    )

    normalized = prepare_report_markdown(content, "final_trade_decision")

    assert "| Metric | Value |" in normalized
    assert "| --- | --- |" in normalized
    assert "### Action\nHOLD" in normalized
    assert "### Final Transaction Proposal\n**HOLD**" in normalized

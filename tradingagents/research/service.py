from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from tradingagents.contracts import (
    EvidenceItem,
    PricingCheck,
    ResearchReport,
    ResearchRequest,
    ResearchVariable,
)
from tradingagents.default_config import DEFAULT_CONFIG


_REPORT_FIELDS = (
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "macro_report",
)


class ResearchRunResult(BaseModel):
    """Result returned by the V2 research façade."""

    schema_version: str = "v2"
    request: ResearchRequest
    report: ResearchReport
    legacy_state: dict[str, Any] = Field(default_factory=dict)
    final_signal: str | None = None
    run_id: str | None = None
    audit_path: str | None = None


@dataclass
class ResearchService:
    """Adapter that exposes a V2 ResearchReport contract.

    This is intentionally a façade over the current legacy graph while the
    dedicated V2 research graph is extracted. The façade disables trade-plan
    persistence so a research/default V2 run does not mutate execution state.
    """

    config: dict[str, Any] | None = None
    graph_factory: Any | None = None

    def run(self, request: ResearchRequest) -> ResearchRunResult:
        cfg = {**DEFAULT_CONFIG, **(self.config or {})}
        cfg["trading_horizon"] = request.horizon
        cfg["output_language"] = request.output_language
        cfg["persist_conditional_trade_plan"] = False
        cfg["v2_research_only"] = True
        if request.source_policy:
            cfg.update(request.source_policy)

        graph_cls = self.graph_factory
        if graph_cls is None:
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            graph_cls = TradingAgentsGraph

        graph = graph_cls(
            selected_analysts=request.selected_analysts,
            config=cfg,
            debug=False,
        )
        final_state, final_signal = graph.propagate(request.symbol, request.trade_date)
        run_id = getattr(graph, "last_run_id", None)
        audit_path = None
        try:
            from tradingagents.run_logger import get_run_audit_logger

            audit_path = get_run_audit_logger().get_run_file_path(run_id=run_id, symbol=request.symbol)
        except Exception:
            audit_path = None
        report = research_report_from_legacy_state(
            final_state,
            request=request,
            final_signal=final_signal,
            run_id=run_id,
            audit_path=audit_path,
        )
        return ResearchRunResult(
            request=request,
            report=report,
            legacy_state=final_state,
            final_signal=final_signal,
            run_id=run_id,
            audit_path=audit_path,
        )


def research_report_from_legacy_state(
    state: dict[str, Any],
    *,
    request: ResearchRequest,
    final_signal: str | None = None,
    run_id: str | None = None,
    audit_path: str | None = None,
) -> ResearchReport:
    """Convert the current full graph state into a V2 ResearchReport.

    The legacy graph still includes portfolio/risk outputs. This adapter keeps
    the report focused on evidence and thesis quality while preserving refs to
    legacy outputs for compatibility/debugging.
    """

    thesis = _extract_thesis(state) or request.thesis or f"{request.symbol} investment thesis"
    final_text = str(state.get("investment_plan") or state.get("final_trade_decision") or "")
    conclusion = _classify_conclusion(final_text, final_signal)
    if final_signal is None and state.get("investment_plan") and not state.get("final_trade_decision"):
        final_signal = _signal_from_conclusion(conclusion)
    confidence = _extract_confidence(final_text)
    reports = {field: str(state.get(field) or "") for field in _REPORT_FIELDS}
    evidence = _evidence_from_reports(reports)
    pricing_check = _pricing_check_from_reports(reports, final_text)
    markdown = _compose_research_markdown(
        request=request,
        thesis=thesis,
        conclusion=conclusion,
        confidence=confidence,
        reports=reports,
        investment_plan=str(state.get("investment_plan") or ""),
    )
    return ResearchReport(
        request_id=request.request_id,
        symbol=request.symbol,
        trade_date=request.trade_date,
        horizon=request.horizon,
        thesis=thesis,
        conclusion=conclusion,
        confidence=confidence,
        variable_map=_default_variables_from_reports(reports),
        evidence_ledger=evidence,
        counter_evidence=_extract_counter_evidence(final_text, reports),
        pricing_check=pricing_check,
        kill_conditions=_extract_kill_conditions(final_text),
        next_sources=_default_next_sources(reports),
        markdown=markdown,
        audit_refs={
            "run_id": run_id,
            "audit_path": audit_path,
            "legacy_fields": [field for field, value in reports.items() if value],
            "final_signal": final_signal,
        },
    )


def _extract_thesis(state: dict[str, Any]) -> str | None:
    for text in (
        state.get("investment_plan"),
        state.get("trader_investment_plan"),
        state.get("final_trade_decision"),
    ):
        text = str(text or "")
        match = re.search(r"\*\*(?:Thesis|交易论点)\*\*:\s*(.+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _classify_conclusion(text: str, final_signal: str | None) -> str:
    lowered = text.lower()
    if "already priced" in lowered or "priced in" in lowered:
        return "C"
    if "unsupported" in lowered or "weak" in lowered or final_signal in {"SELL", "SHORT"}:
        return "D"
    if final_signal in {"BUY", "LONG"} and "high confidence" in lowered:
        return "A"
    return "B"


def _signal_from_conclusion(conclusion: str) -> str:
    if conclusion in {"A", "B"}:
        return "BUY"
    if conclusion == "C":
        return "HOLD"
    return "SELL"


def _extract_confidence(text: str) -> str:
    match = re.search(r"confidence\**\s*:\s*([A-Za-z]+)", text, flags=re.IGNORECASE)
    if match:
        value = match.group(1).strip().lower()
        if value in {"high", "medium", "low"}:
            return value
    lowered = text.lower()
    if "low confidence" in lowered:
        return "low"
    if "high confidence" in lowered:
        return "high"
    return "medium"


def _evidence_from_reports(reports: dict[str, str]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for field, text in reports.items():
        snippet = _first_substantial_line(text)
        if not snippet:
            continue
        items.append(
            EvidenceItem(
                source_label=field,
                evidence=snippet[:700],
                direction="mixed",
                variable=field.replace("_report", ""),
                strength="Inference",
            )
        )
    return items


def _default_variables_from_reports(reports: dict[str, str]) -> list[ResearchVariable]:
    variables: list[ResearchVariable] = []
    mapping = {
        "market_report": ("price action and trend", "market", "valuation multiple / market narrative"),
        "sentiment_report": ("social sentiment", "market narrative", "market narrative"),
        "news_report": ("news catalysts", "catalyst", "revenue / market narrative"),
        "fundamentals_report": ("fundamentals", "fundamentals", "revenue / margin / free cash flow"),
        "macro_report": ("macro regime", "macro", "valuation multiple / liquidity"),
    }
    for field, text in reports.items():
        if not text:
            continue
        name, bucket, line_item = mapping[field]
        variables.append(
            ResearchVariable(
                name=name,
                bucket=bucket,
                affected_line_item=line_item,
                why_it_matters="Derived from legacy analyst report availability.",
                verification_need=f"Review {field} evidence and source freshness.",
            )
        )
    return variables


def _pricing_check_from_reports(reports: dict[str, str], final_text: str) -> PricingCheck:
    combined = "\n".join([*reports.values(), final_text]).lower()
    checked = any(term in combined for term in ("valuation", "priced", "multiple", "consensus", "guidance"))
    missing = []
    if "valuation" not in combined and "multiple" not in combined:
        missing.append("valuation")
    if "consensus" not in combined and "guidance" not in combined:
        missing.append("consensus_or_guidance")
    return PricingCheck(
        checked=checked,
        stock_performance="See market_report." if reports.get("market_report") else None,
        valuation="See fundamentals/final decision text." if checked else None,
        consensus_or_guidance="See fundamentals/news reports." if "guidance" in combined or "consensus" in combined else None,
        expectation_gap="See final decision rationale." if "priced" in combined else None,
        missing=missing,
    )


def _extract_counter_evidence(final_text: str, reports: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    for line in final_text.splitlines():
        lower = line.lower()
        if any(term in lower for term in ("risk", "bear", "downside", "headwind", "counter")):
            cleaned = line.strip("- ").strip()
            if cleaned:
                candidates.append(cleaned[:400])
    if not candidates:
        for field in ("macro_report", "fundamentals_report", "news_report"):
            snippet = _first_substantial_line(reports.get(field, ""))
            if snippet:
                candidates.append(f"Review {field}: {snippet[:260]}")
    return candidates[:5]


def _extract_kill_conditions(final_text: str) -> list[str]:
    conditions: list[str] = []
    capture = False
    for line in final_text.splitlines():
        lower = line.lower()
        if "kill" in lower or "invalidation" in lower or "失效" in lower:
            capture = True
        if capture:
            cleaned = line.strip("- ").strip()
            if cleaned:
                conditions.append(cleaned[:400])
        if len(conditions) >= 5:
            break
    return conditions or ["Evidence weakens materially or explicit invalidation in the portfolio decision is breached."]


def _default_next_sources(reports: dict[str, str]) -> list[str]:
    missing = [field for field, text in reports.items() if not text]
    if missing:
        return [f"Re-run or inspect missing {field}" for field in missing[:5]]
    return [
        "Latest 10-Q/10-K or investor presentation",
        "Most recent earnings call transcript",
        "Current valuation and consensus snapshot",
        "Primary news/catalyst source",
        "Point-in-time market data quality record",
    ]


def _compose_research_markdown(
    *,
    request: ResearchRequest,
    thesis: str,
    conclusion: str,
    confidence: str,
    reports: dict[str, str],
    investment_plan: str,
) -> str:
    parts = [
        f"# Research Report: {request.symbol}",
        "",
        f"- Trade date: {request.trade_date}",
        f"- Horizon: {request.horizon}",
        f"- Conclusion: {conclusion}",
        f"- Confidence: {confidence}",
        "",
        "## Thesis",
        thesis,
        "",
        "## Analyst Report Summary",
    ]
    for field, text in reports.items():
        snippet = _first_substantial_line(text) or "No report content available."
        parts.append(f"- {field}: {snippet[:500]}")
    if investment_plan:
        parts.extend(["", "## Legacy Research Manager Output", investment_plan])
    return "\n".join(parts)


def _first_substantial_line(text: str) -> str:
    for line in str(text or "").splitlines():
        cleaned = line.strip()
        if len(cleaned) >= 40:
            return cleaned
    return str(text or "").strip()[:500]

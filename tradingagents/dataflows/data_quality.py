from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .freshness import date_age_days, freshest_date_in_text, parse_date


QUALITY_STATUSES = ("pass", "warn", "fail", "unknown")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DataSourceSpec:
    source_id: str
    provider: str
    dataset_type: str
    freshness_sla_days: int | None
    criticality: str = "medium"
    fallbacks: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()


@dataclass
class DataQualityResult:
    status: str
    freshness: str = "unknown"
    accuracy: str = "unknown"
    completeness: str = "unknown"
    flags: list[str] = field(default_factory=list)
    observed_at: str | None = None
    fetched_at: str = field(default_factory=_utc_now_iso)
    cache_hit: bool | None = None
    fallback_from: str | None = None
    source_age_days: int | None = None
    source_id: str = "unknown"
    provider: str = "unknown"
    dataset_type: str = "unknown"
    criticality: str = "medium"
    validator: str = "generic_text_quality_v1"
    artifact_ref: str | None = None
    output_chars: int = 0
    output_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["flags"] = sorted(set(str(flag) for flag in self.flags if str(flag).strip()))
        return data


@dataclass
class EvidenceArtifact:
    tool_name: str
    symbol: str | None
    source_id: str
    requested_window: dict[str, Any] = field(default_factory=dict)
    raw_output_ref: str | None = None
    quality: DataQualityResult | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.quality is not None:
            data["quality"] = self.quality.to_dict()
        return data


UNKNOWN_SOURCE_SPEC = DataSourceSpec(
    source_id="unknown",
    provider="unknown",
    dataset_type="unknown",
    freshness_sla_days=None,
    criticality="low",
    checks=("text_nonempty",),
)


TOOL_SOURCE_SPECS: dict[str, DataSourceSpec] = {
    "get_sellthenews_stock_news": DataSourceSpec("sellthenews_stock_news", "SellTheNews", "news", 2, "high", ("google_news", "finnhub_news"), ("published_at", "ticker_relevance")),
    "get_sellthenews_social_sentiment": DataSourceSpec("sellthenews_social", "SellTheNews", "social", 2, "medium", ("reddit", "stocktwits"), ("sample_count", "ticker_relevance")),
    "get_sellthenews_macro_news": DataSourceSpec("sellthenews_macro_news", "SellTheNews", "macro_news", 3, "medium", ("fred", "openai_web_search"), ("published_at",)),
    "get_sellthenews_options_data": DataSourceSpec("sellthenews_options", "SellTheNews", "options", 1, "medium", (), ("spot_present", "expiration_present", "gamma_flip", "call_wall", "put_wall", "max_pain")),
    "get_reddit_news": DataSourceSpec("reddit_global_news", "Reddit", "news", 7, "low", (), ("sample_count", "published_at")),
    "get_reddit_stock_info": DataSourceSpec("reddit_company_news", "Reddit", "social", 7, "medium", ("stocktwits",), ("sample_count", "ticker_relevance")),
    "get_finnhub_news_recent": DataSourceSpec("finnhub_news", "Finnhub", "news", 7, "high", ("google_news",), ("published_at", "ticker_relevance")),
    "get_finnhub_news": DataSourceSpec("finnhub_news", "Finnhub", "news", 7, "high", ("google_news",), ("published_at", "ticker_relevance")),
    "get_google_news": DataSourceSpec("google_news", "GoogleNews", "news", 7, "medium", (), ("published_at", "ticker_relevance")),
    "get_stock_news_openai": DataSourceSpec("openai_stock_news", "OpenAI web_search", "news", 7, "medium", (), ("published_at", "ticker_relevance")),
    "get_global_news_openai": DataSourceSpec("openai_global_news", "OpenAI web_search", "news", 7, "medium", (), ("published_at",)),
    "get_macro_news_openai": DataSourceSpec("openai_macro_news", "OpenAI web_search", "macro_news", 7, "medium", (), ("published_at",)),
    "get_coindesk_news": DataSourceSpec("coindesk_crypto_news", "CoinDesk/CryptoCompare", "news", 7, "medium", (), ("published_at", "ticker_relevance")),
    "get_alpaca_data": DataSourceSpec("alpaca_bars", "Alpaca", "price_bars", 2, "critical", ("yfinance",), ("ohlcv_schema", "latest_bar")),
    "get_alpaca_data_report": DataSourceSpec("alpaca_bars", "Alpaca", "price_bars", 2, "critical", ("yfinance",), ("ohlcv_schema", "latest_bar")),
    "get_stock_data_table": DataSourceSpec("alpaca_bars", "Alpaca", "price_bars", 2, "critical", ("yfinance",), ("ohlcv_schema", "latest_bar")),
    "get_technical_brief": DataSourceSpec("technical_brief", "Alpaca/stockstats", "technical_indicators", 5, "high", ("alpaca_bars",), ("indicator_schema", "latest_bar")),
    "get_trend_brief": DataSourceSpec("trend_brief", "Alpaca/stockstats", "technical_indicators", 10, "high", ("alpaca_bars",), ("indicator_schema", "latest_bar")),
    "get_stockstats_indicators_report": DataSourceSpec("stockstats_indicators", "stockstats", "technical_indicators", 5, "high", ("alpaca_bars",), ("indicator_schema", "latest_bar")),
    "get_stockstats_indicators_report_online": DataSourceSpec("stockstats_indicators", "stockstats", "technical_indicators", 5, "high", ("alpaca_bars",), ("indicator_schema", "latest_bar")),
    "get_indicators_table": DataSourceSpec("stockstats_indicators", "stockstats", "technical_indicators", 5, "high", ("alpaca_bars",), ("indicator_schema", "latest_bar")),
    "get_finnhub_company_insider_sentiment": DataSourceSpec("finnhub_insider_sentiment", "Finnhub", "fundamentals", 45, "medium", ("sec_edgar",), ("date_window",)),
    "get_finnhub_company_insider_transactions": DataSourceSpec("finnhub_insider_transactions", "Finnhub", "fundamentals", 45, "medium", ("sec_edgar",), ("date_window",)),
    "get_finnhub_company_fundamentals": DataSourceSpec("finnhub_fundamentals", "Finnhub", "fundamentals", 540, "medium", ("sec_edgar",), ("metric_recency",)),
    "get_sec_edgar_fundamentals": DataSourceSpec("sec_edgar_fundamentals", "SEC EDGAR", "filings", 540, "critical", (), ("filing_recency", "official_source")),
    "get_alpha_vantage_fundamentals": DataSourceSpec("alpha_vantage_fundamentals", "Alpha Vantage MCP", "fundamentals", 540, "medium", ("sec_edgar", "finnhub"), ("metric_recency",)),
    "get_fundamentals_openai": DataSourceSpec("openai_fundamentals", "OpenAI web_search", "fundamentals", 45, "low", ("sec_edgar", "finnhub"), ("source_citations",)),
    "get_simfin_balance_sheet": DataSourceSpec("simfin_balance_sheet", "SimFin local", "fundamentals", 540, "medium", ("sec_edgar",), ("metric_recency",)),
    "get_simfin_cashflow": DataSourceSpec("simfin_cashflow", "SimFin local", "fundamentals", 540, "medium", ("sec_edgar",), ("metric_recency",)),
    "get_simfin_income_stmt": DataSourceSpec("simfin_income_statement", "SimFin local", "fundamentals", 540, "medium", ("sec_edgar",), ("metric_recency",)),
    "get_earnings_calendar": DataSourceSpec("earnings_calendar", "Finnhub/events", "fundamentals", 120, "medium", (), ("event_dates",)),
    "get_earnings_surprise_analysis": DataSourceSpec("earnings_surprises", "Finnhub/events", "fundamentals", 540, "medium", (), ("event_dates",)),
    "get_defillama_fundamentals": DataSourceSpec("defillama_fundamentals", "DeFiLlama", "crypto_fundamentals", 7, "medium", (), ("latest_observation",)),
    "get_macro_analysis": DataSourceSpec("macro_analysis", "FRED/macro", "macro", 45, "medium", (), ("latest_observation",)),
    "get_economic_indicators": DataSourceSpec("economic_indicators", "FRED/macro", "macro", 45, "medium", (), ("latest_observation",)),
    "get_yield_curve_analysis": DataSourceSpec("treasury_yield_curve", "Treasury/FRED", "macro", 7, "medium", (), ("latest_observation",)),
}


def get_source_spec(tool_name: str) -> DataSourceSpec:
    return TOOL_SOURCE_SPECS.get(str(tool_name or ""), UNKNOWN_SOURCE_SPEC)


def _input_date(inputs: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = inputs.get(key)
        parsed = parse_date(value)
        if parsed is not None:
            return parsed.isoformat()
    return None


def requested_window_from_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    window: dict[str, Any] = {}
    for key in ("symbol", "ticker", "query", "ticker_context"):
        if inputs.get(key):
            window[key] = inputs.get(key)
            break
    for key in ("start_date", "end_date", "curr_date", "look_back_days", "lookback_days", "timeframe"):
        if key in inputs:
            window[key] = inputs.get(key)
    return window


def symbol_from_inputs(inputs: dict[str, Any]) -> str | None:
    for key in ("symbol", "ticker", "query", "ticker_context"):
        value = inputs.get(key)
        if value:
            return str(value)
    return None


def _fallback_from_text(text: str, spec: DataSourceSpec) -> str | None:
    lower = text.lower()
    if "yfinance" in lower or "yahoo" in lower:
        return "yfinance"
    if "fallback" not in lower:
        return None
    return spec.provider


def _has_any(text: str, needles: Iterable[str]) -> bool:
    lower = text.lower()
    return any(needle in lower for needle in needles)


def _looks_source_unavailable(lower: str) -> bool:
    if lower.startswith(("error", "exception")):
        return True
    unavailable_patterns = (
        "source unavailable",
        "source was unavailable",
        "unavailable or sparse",
        "could not be loaded",
        "api key not found",
        "tool timeout",
    )
    if any(pattern in lower for pattern in unavailable_patterns):
        return True
    return re.search(
        r"\b(?:mcp|api|source|tool|service|sec edgar|alpha vantage|sellthenews|openai)[^\n]{0,80}\bunavailable\b",
        lower,
    ) is not None


def _explicit_as_of_date(text: str) -> str | None:
    for pattern in (
        r"\bas of\s+(\d{4}-\d{2}-\d{2})",
        r"\bUpdated:\s*(\d{4}-\d{2}-\d{2})",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date(match.group(1))
            if parsed is not None:
                return parsed.isoformat()
    return None


def _observed_date_from_payload(text: str, tool_name: str, inputs: dict[str, Any] | None = None) -> str | None:
    source_id = get_source_spec(tool_name).source_id
    inputs = inputs or {}
    if source_id == "sellthenews_options":
        # Options reports contain many future expiration dates. Do not let the
        # generic "freshest date in text" parser treat a LEAPS expiry as the
        # observation timestamp. The API response is fetched live for curr_date,
        # and the report header carries that as the as-of date.
        return _input_date(inputs, ("curr_date", "as_of", "end_date"))
    if source_id in {
        "sellthenews_social",
        "finnhub_fundamentals",
        "alpha_vantage_fundamentals",
        "sec_edgar_fundamentals",
    }:
        # These reports can contain future metric periods, contract dates, or
        # event dates. Prefer the report's explicit as-of date, then the tool's
        # PIT request boundary, instead of the generic freshest-date scan.
        return _explicit_as_of_date(text) or _input_date(inputs, ("curr_date", "as_of", "end_date"))
    if source_id not in {"technical_brief", "trend_brief"}:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("observed_at", "latest_bar_date", "last_bar_date", "generated_at"):
        parsed = parse_date(payload.get(key))
        if parsed is not None:
            return parsed.isoformat()
    raw_prices = payload.get("raw_prices")
    if isinstance(raw_prices, dict):
        for key in ("observed_at", "latest_bar_date", "last_bar_date"):
            parsed = parse_date(raw_prices.get(key))
            if parsed is not None:
                return parsed.isoformat()
    return None


def _has_options_required_levels(text: str) -> bool:
    labels = ("Gamma Flip", "Call Wall", "Put Wall", "Max Pain")
    for label in labels:
        match = re.search(rf"{re.escape(label)}:\s*\$?(?:unknown|none|n/a|nan)?", text, flags=re.IGNORECASE)
        if not match:
            return False
        tail = text[match.start() : match.start() + 80]
        if re.search(rf"{re.escape(label)}:\s*\$?\s*-?\d+(?:\.\d+)?", tail, flags=re.IGNORECASE) is None:
            return False
    return True


def evaluate_tool_output(
    tool_name: str,
    inputs: dict[str, Any] | None,
    output: Any,
    *,
    text_quality: dict[str, Any] | None = None,
    artifact_ref: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = inputs or {}
    text = str(output or "")
    lower = text.lower()
    spec = get_source_spec(tool_name)
    flags = list((text_quality or {}).get("flags", []) or [])
    output_chars = len(text)

    if spec.source_id == "unknown":
        flags.append("unregistered_tool_source")

    if not text.strip():
        flags.append("empty_output")
    if _looks_source_unavailable(lower):
        flags.append("source_unavailable")
    if "fallback" in lower:
        flags.append("fallback_used")

    fallback_from = _fallback_from_text(text, spec)

    as_of = _input_date(inputs, ("end_date", "curr_date", "as_of")) or _utc_now_iso()[:10]
    observed_at = _observed_date_from_payload(text, tool_name, inputs)
    observed = parse_date(observed_at) if observed_at is not None else None
    if observed is None:
        observed = freshest_date_in_text(text)
        observed_at = observed.isoformat() if observed is not None else None
    age_days = date_age_days(observed, as_of=as_of) if observed is not None else None

    freshness = "unknown"
    if observed is None:
        if spec.freshness_sla_days is not None and spec.dataset_type in {"news", "social", "price_bars", "technical_indicators", "macro", "macro_news"}:
            flags.append("missing_observed_timestamp")
            freshness = "warn"
    elif spec.freshness_sla_days is not None and age_days is not None:
        if age_days < -1:
            flags.append("future_observed_timestamp")
            freshness = "warn"
        elif age_days > spec.freshness_sla_days:
            flags.append("stale_source")
            freshness = "fail" if spec.criticality == "critical" else "warn"
        else:
            freshness = "pass"

    completeness = "pass"
    if "empty_output" in flags:
        completeness = "fail"
    elif "undersized_output" in flags or "missing_observed_timestamp" in flags:
        completeness = "warn"

    accuracy = "unknown"
    if spec.dataset_type == "price_bars":
        if not _has_any(text, ("open", "high", "low", "close", "volume")):
            flags.append("missing_ohlcv_schema")
            completeness = "fail"
        elif _has_any(text, ("open", "high", "low", "close", "volume")):
            accuracy = "pass"
    elif spec.source_id == "sellthenews_options":
        if not _has_options_required_levels(text):
            flags.append("missing_required_options_levels")
            completeness = "warn"
        elif "spot price:" in lower and "selected expiration:" in lower:
            accuracy = "pass"
    elif spec.source_id == "sec_edgar_fundamentals" and "official filing" in lower:
        accuracy = "pass"
    elif spec.dataset_type in {"news", "social", "macro_news"} and ("http" in lower or "source" in lower or "published" in lower):
        accuracy = "pass"

    severe_flags = {"empty_output", "source_unavailable", "missing_ohlcv_schema"}
    status = "pass"
    if spec.source_id == "unknown":
        status = "unknown"
    if any(flag in flags for flag in severe_flags):
        status = "fail" if spec.criticality == "critical" else "warn"
    elif freshness == "fail":
        status = "fail"
    elif flags or freshness == "warn" or completeness == "warn":
        status = "warn"
    elif freshness == "unknown" and accuracy == "unknown":
        status = "unknown"

    result = DataQualityResult(
        status=status if status in QUALITY_STATUSES else "unknown",
        freshness=freshness,
        accuracy=accuracy,
        completeness=completeness,
        flags=flags,
        observed_at=observed_at,
        fallback_from=fallback_from,
        source_age_days=age_days,
        source_id=spec.source_id,
        provider=spec.provider,
        dataset_type=spec.dataset_type,
        criticality=spec.criticality,
        artifact_ref=artifact_ref,
        output_chars=output_chars,
        output_preview=text.strip()[:240],
    )
    artifact = EvidenceArtifact(
        tool_name=str(tool_name or "unknown"),
        symbol=symbol_from_inputs(inputs),
        source_id=spec.source_id,
        requested_window=requested_window_from_inputs(inputs),
        raw_output_ref=artifact_ref,
        quality=result,
    )
    return {
        **result.to_dict(),
        "artifact": artifact.to_dict(),
    }


def build_quality_header(quality: dict[str, Any]) -> str:
    flags = ",".join(quality.get("flags") or [])
    lines = [
        "[DATA_QUALITY]",
        f"status: {quality.get('status', 'unknown')}",
        f"source_id: {quality.get('source_id', 'unknown')}",
        f"dataset_type: {quality.get('dataset_type', 'unknown')}",
        f"observed_at: {quality.get('observed_at') or 'unknown'}",
        f"freshness: {quality.get('freshness', 'unknown')}",
        f"accuracy: {quality.get('accuracy', 'unknown')}",
        f"flags: {flags or 'none'}",
        f"artifact_ref: {quality.get('artifact_ref') or 'unknown'}",
        "[/DATA_QUALITY]",
        "",
    ]
    return "\n".join(lines)


def prepend_quality_header(output: Any, quality: dict[str, Any]) -> str:
    text = str(output or "")
    if text.lstrip().startswith("[DATA_QUALITY]"):
        return text
    return build_quality_header(quality) + text


def load_audit_payload(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def find_audit_path(run_id: str, *, root: str | Path = "eval_results") -> Path | None:
    candidates = list(Path(root).glob(f"*/TradingAgentsStrategy_logs/runs/{run_id}.json"))
    return candidates[0] if candidates else None


def quality_events_from_audit(audit: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    tool_index = 0
    for event in audit.get("events", []) or []:
        if event.get("type") != "tool_call":
            continue
        tool_index += 1
        payload = event.get("payload") or {}
        quality = (payload.get("quality_details") or {}).get("data_quality")
        if not isinstance(quality, dict):
            quality = payload.get("quality_details") or {}
        artifact_ref = quality.get("artifact_ref") or f"tool_call:{tool_index}"
        events.append(
            {
                "timestamp": event.get("timestamp"),
                "artifact_ref": artifact_ref,
                "tool_index": tool_index,
                "tool_name": payload.get("tool_name"),
                "agent_type": payload.get("agent_type"),
                "symbol": payload.get("symbol") or audit.get("symbol"),
                "status": quality.get("status", "unknown"),
                "source_id": quality.get("source_id", "unknown"),
                "provider": quality.get("provider", "unknown"),
                "dataset_type": quality.get("dataset_type", "unknown"),
                "freshness": quality.get("freshness", "unknown"),
                "accuracy": quality.get("accuracy", "unknown"),
                "completeness": quality.get("completeness", "unknown"),
                "flags": quality.get("flags", []) or [],
                "observed_at": quality.get("observed_at"),
                "source_age_days": quality.get("source_age_days"),
                "fallback_from": quality.get("fallback_from"),
                "criticality": quality.get("criticality"),
                "output_preview": quality.get("output_preview") or str(payload.get("output", ""))[:240],
                "inputs": payload.get("inputs") or {},
            }
        )
    return events


def summarize_quality_events(
    events: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    symbol: str | None = None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    counts = {status: 0 for status in QUALITY_STATUSES}
    source_statuses: dict[str, dict[str, Any]] = {}
    fallback_sources: list[str] = []
    stale_sources: list[str] = []
    critical_failures: list[str] = []

    for event in events:
        status = event.get("status") if event.get("status") in QUALITY_STATUSES else "unknown"
        counts[status] += 1
        source_id = str(event.get("source_id") or "unknown")
        current = source_statuses.setdefault(
            source_id,
            {
                "source_id": source_id,
                "provider": event.get("provider"),
                "dataset_type": event.get("dataset_type"),
                "status": status,
                "events": 0,
                "flags": [],
                "latest_observed_at": None,
                "artifact_refs": [],
            },
        )
        current["events"] += 1
        current["artifact_refs"].append(event.get("artifact_ref"))
        current["flags"] = sorted(set(current.get("flags", []) + list(event.get("flags") or [])))
        if _status_rank(status) > _status_rank(current.get("status")):
            current["status"] = status
        if event.get("observed_at"):
            current["latest_observed_at"] = max(
                str(current.get("latest_observed_at") or event["observed_at"]),
                str(event["observed_at"]),
            )
        if event.get("fallback_from"):
            fallback_sources.append(source_id)
        if "stale_source" in (event.get("flags") or []):
            stale_sources.append(source_id)
        if status == "fail" and event.get("criticality") == "critical":
            critical_failures.append(source_id)

    top_risks = [
        event
        for event in events
        if event.get("status") in {"fail", "warn"} or event.get("flags")
    ][:10]
    artifact_refs = [
        {
            "artifact_ref": event.get("artifact_ref"),
            "tool_name": event.get("tool_name"),
            "source_id": event.get("source_id"),
            "status": event.get("status"),
        }
        for event in events
    ]
    return {
        "run_id": run_id,
        "symbol": symbol,
        "trade_date": trade_date,
        "summary": {
            "total_events": len(events),
            "quality_pass": counts["pass"],
            "quality_warn": counts["warn"],
            "quality_fail": counts["fail"],
            "quality_unknown": counts["unknown"],
            "stale_sources": sorted(set(stale_sources)),
            "fallback_sources": sorted(set(fallback_sources)),
            "critical_failures": sorted(set(critical_failures)),
        },
        "top_risks": top_risks,
        "source_statuses": sorted(source_statuses.values(), key=lambda item: item["source_id"]),
        "artifact_refs": artifact_refs,
        "recommended_debug_queries": [
            "python -m cli.main quality-events --audit-path <path> --status warn,fail --format jsonl",
            "python -m cli.main quality-open --audit-path <path> --artifact-ref tool_call:1",
        ],
    }


def _status_rank(status: str | None) -> int:
    return {"pass": 0, "unknown": 1, "warn": 2, "fail": 3}.get(str(status or "unknown"), 1)


def open_artifact_from_audit(audit: dict[str, Any], artifact_ref: str) -> dict[str, Any] | None:
    match = re.match(r"tool_call:(\d+)$", str(artifact_ref or ""))
    if not match:
        return None
    target = int(match.group(1))
    tool_index = 0
    for event in audit.get("events", []) or []:
        if event.get("type") != "tool_call":
            continue
        tool_index += 1
        if tool_index != target:
            continue
        payload = event.get("payload") or {}
        return {
            "artifact_ref": artifact_ref,
            "timestamp": event.get("timestamp"),
            "tool_name": payload.get("tool_name"),
            "agent_type": payload.get("agent_type"),
            "inputs": payload.get("inputs") or {},
            "status": payload.get("status"),
            "quality_details": payload.get("quality_details") or {},
            "output": payload.get("output"),
        }
    return None

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import time
from typing import Any

import requests

from .config import get_config


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"
DEFAULT_USER_AGENT = "AlpacaTradingAgent SEC-EDGAR research contact@example.com"

METRIC_TAGS = {
    "revenue": ("USD", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]),
    "gross_profit": ("USD", ["GrossProfit"]),
    "operating_income": ("USD", ["OperatingIncomeLoss"]),
    "net_income": ("USD", ["NetIncomeLoss"]),
    "cash": ("USD", ["CashAndCashEquivalentsAtCarryingValue"]),
    "debt": ("USD", ["LongTermDebtCurrent", "LongTermDebtNoncurrent", "DebtCurrent", "LongTermDebt"]),
    "operating_cash_flow": ("USD", ["NetCashProvidedByUsedInOperatingActivities"]),
    "shares_outstanding": (
        "shares",
        ["EntityCommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"],
    ),
}

PERIODIC_FORMS = {"10-Q", "10-K", "20-F", "40-F"}
PERIODIC_FILING_FORMS = ("10-Q", "10-K", "20-F", "40-F")
RECENT_FILING_FORMS = ("10-K", "10-Q", "8-K", "20-F", "40-F", "6-K")
DISPLAY_FILING_FORMS = ("10-K", "10-Q", "8-K")
FOREIGN_FILING_FORMS = ("20-F", "40-F", "6-K")


class SecEdgarUnavailable(RuntimeError):
    pass


def get_sec_edgar_fundamentals(ticker: str, curr_date: str, config: dict | None = None) -> str:
    cfg = {**get_config(), **(config or {})}
    if not _coerce_bool(cfg.get("online_tools", True)) or not _coerce_bool(cfg.get("sec_edgar_enabled", True)):
        return f"## SEC EDGAR Fundamentals for {ticker}: unavailable because SEC EDGAR is disabled."
    try:
        cik, identity = resolve_cik(ticker, cfg)
        submissions = fetch_submissions(cik, cfg)
        facts = fetch_companyfacts(cik, cfg)
        filings = latest_filings(submissions, cik, as_of=curr_date)
        parsed = parse_companyfacts(
            facts,
            max_points=int(cfg.get("sec_edgar_max_quarters", 8)),
            latest_period_end=_latest_period_end(filings),
            stale_days=int(cfg.get("sec_edgar_metric_stale_days", 540)),
            as_of=curr_date,
        )
        return format_sec_report(
            ticker=ticker,
            curr_date=curr_date,
            cik=cik,
            identity=identity,
            filings=filings,
            parsed_facts=parsed,
        )
    except Exception as exc:
        return (
            f"## SEC EDGAR Fundamentals for {ticker}: unavailable\n\n"
            f"SEC EDGAR official filing source could not be loaded: {type(exc).__name__}: {exc}"
        )


def sec_fundamental_confirmation(ticker: str, curr_date: str | None = None, config: dict | None = None) -> dict[str, Any]:
    cfg = {**get_config(), **(config or {})}
    cik, identity = resolve_cik(ticker, cfg)
    submissions = fetch_submissions(cik, cfg)
    facts = fetch_companyfacts(cik, cfg)
    filings = latest_filings(submissions, cik, as_of=curr_date)
    parsed = parse_companyfacts(
        facts,
        max_points=int(cfg.get("sec_edgar_max_quarters", 8)),
        latest_period_end=_latest_period_end(filings),
        stale_days=int(cfg.get("sec_edgar_metric_stale_days", 540)),
        as_of=curr_date,
    )
    flags = _fundamental_flags(parsed, filings, curr_date)
    has_recent = "recent_filing_available" in flags and "filing_stale" not in flags
    risk_flags = [flag for flag in flags if flag in {"filing_stale", "margin_deterioration", "cash_debt_risk"}]
    return {
        "confirmed": has_recent,
        "strength": 0.06 if has_recent and not risk_flags else 0.03,
        "flags": flags,
        "risk_flags": risk_flags,
        "cik": cik,
        "company_name": identity.get("title") or identity.get("name") or ticker.upper(),
        "summary": _compact_confirmation_summary(parsed, filings, flags),
    }


def resolve_cik(ticker: str, config: dict | None = None) -> tuple[str, dict[str, Any]]:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise SecEdgarUnavailable("empty ticker")
    mapping = get_ticker_cik_map(config)
    item = mapping.get(symbol)
    if not item:
        raise SecEdgarUnavailable(f"ticker {symbol} not found in SEC mapping")
    cik = str(item["cik_str"]).zfill(10)
    return cik, item


def get_ticker_cik_map(config: dict | None = None) -> dict[str, dict[str, Any]]:
    cfg = {**get_config(), **(config or {})}
    ttl_seconds = int(float(cfg.get("sec_edgar_mapping_cache_ttl_days", 7)) * 86400)
    cached = _read_cache("company_tickers", ttl_seconds, cfg)
    if isinstance(cached, dict):
        return cached
    payload = _request_json(SEC_TICKERS_URL, cfg)
    result = {}
    for item in payload.values() if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper()
        if ticker:
            result[ticker] = item
    if not result:
        raise SecEdgarUnavailable("SEC ticker mapping was empty")
    _write_cache("company_tickers", result, cfg)
    return result


def fetch_submissions(cik: str, config: dict | None = None) -> dict[str, Any]:
    cfg = {**get_config(), **(config or {})}
    cache_key = f"submissions_{cik}"
    cached = _read_cache(cache_key, int(float(cfg.get("sec_edgar_cache_ttl_hours", 24)) * 3600), cfg)
    if isinstance(cached, dict):
        return cached
    payload = _request_json(SEC_SUBMISSIONS_URL.format(cik=cik), cfg)
    _write_cache(cache_key, payload, cfg)
    return payload


def fetch_companyfacts(cik: str, config: dict | None = None) -> dict[str, Any]:
    cfg = {**get_config(), **(config or {})}
    cache_key = f"companyfacts_{cik}"
    cached = _read_cache(cache_key, int(float(cfg.get("sec_edgar_cache_ttl_hours", 24)) * 3600), cfg)
    if isinstance(cached, dict):
        return cached
    payload = _request_json(SEC_COMPANYFACTS_URL.format(cik=cik), cfg)
    _write_cache(cache_key, payload, cfg)
    return payload


def parse_companyfacts(
    companyfacts: dict[str, Any],
    *,
    max_points: int = 8,
    latest_period_end: str | None = None,
    stale_days: int = 540,
    as_of: str | None = None,
) -> dict[str, Any]:
    us_gaap = ((companyfacts.get("facts") or {}).get("us-gaap") or {}) if isinstance(companyfacts, dict) else {}
    metrics: dict[str, Any] = {}
    warnings: list[str] = []
    for metric, (unit, tags) in METRIC_TAGS.items():
        metrics[metric] = _select_metric(us_gaap, tags, unit, max_points=max_points, as_of=as_of)
        _apply_metric_freshness_gate(metric, metrics[metric], latest_period_end, stale_days)
        if metrics[metric].get("warning"):
            warnings.append(metrics[metric]["warning"])
    return {
        "entity_name": companyfacts.get("entityName") if isinstance(companyfacts, dict) else None,
        "metrics": metrics,
        "warnings": warnings,
    }


def latest_filings(submissions: dict[str, Any], cik: str, as_of: str | None = None) -> dict[str, Any]:
    recent = ((submissions.get("filings") or {}).get("recent") or {}) if isinstance(submissions, dict) else {}
    rows = []
    forms = recent.get("form") or []
    for index, form in enumerate(forms):
        row = {
            "form": form,
            "filing_date": _list_get(recent.get("filingDate"), index),
            "report_date": _list_get(recent.get("reportDate"), index),
            "accession_number": _list_get(recent.get("accessionNumber"), index),
            "primary_document": _list_get(recent.get("primaryDocument"), index),
        }
        if as_of and not _date_lte(row.get("filing_date"), as_of):
            continue
        row["url"] = _filing_url(cik, row["accession_number"], row["primary_document"])
        rows.append(row)
    latest = {}
    for form in RECENT_FILING_FORMS:
        latest[form] = next((row for row in rows if row.get("form") == form), None)
    return latest


def format_sec_report(
    *,
    ticker: str,
    curr_date: str,
    cik: str,
    identity: dict[str, Any],
    filings: dict[str, Any],
    parsed_facts: dict[str, Any],
) -> str:
    name = parsed_facts.get("entity_name") or identity.get("title") or identity.get("name") or ticker.upper()
    flags = _fundamental_flags(parsed_facts, filings, curr_date)
    lines = [
        f"## SEC EDGAR Official Fundamentals for {ticker.upper()} as of {curr_date}",
        "",
        f"Company: {name}",
        f"CIK: {cik}",
        "",
        "### Latest SEC filings",
    ]
    forms_to_show = list(DISPLAY_FILING_FORMS)
    forms_to_show.extend(form for form in FOREIGN_FILING_FORMS if filings.get(form))
    for form in forms_to_show:
        filing = filings.get(form)
        if filing:
            lines.append(
                f"- {form}: filed {filing.get('filing_date') or 'N/A'}, "
                f"period {filing.get('report_date') or 'N/A'}, accession {filing.get('accession_number') or 'N/A'}, "
                f"url {filing.get('url') or 'N/A'}"
            )
        else:
            lines.append(f"- {form}: missing")
    lines.extend(["", "### Filing quality flags"])
    lines.append("- " + "; ".join(flags) if flags else "- no filing freshness warnings")
    if parsed_facts.get("warnings"):
        lines.append("- " + "; ".join(parsed_facts["warnings"][:6]))
    lines.extend(["", "### Structured XBRL facts"])
    for metric, data in (parsed_facts.get("metrics") or {}).items():
        lines.append(_format_metric(metric, data))
    lines.extend(
        [
            "",
            "Note: SEC EDGAR is the official filing source. Values are structured XBRL facts; do not mix periods unless the period/end date matches.",
        ]
    )
    return "\n".join(lines).strip()


def _select_metric(
    us_gaap: dict[str, Any],
    tags: list[str],
    unit: str,
    *,
    max_points: int,
    as_of: str | None = None,
) -> dict[str, Any]:
    saw_non_usd = False
    candidates: list[dict[str, Any]] = []
    for tag in tags:
        payload = us_gaap.get(tag)
        units = (payload or {}).get("units") if isinstance(payload, dict) else None
        if not isinstance(units, dict):
            continue
        if unit not in units:
            if unit == "USD" and units:
                saw_non_usd = True
            continue
        facts = _clean_facts(units.get(unit), max_points=max_points, as_of=as_of)
        if facts:
            candidates.append({"tag": tag, "unit": unit, "facts": facts, "priority": len(candidates)})
    if candidates:
        newest_end = max(str((candidate["facts"][0] or {}).get("end") or "") for candidate in candidates)
        fresh_candidates = [
            candidate
            for candidate in candidates
            if _days_between((candidate["facts"][0] or {}).get("end"), newest_end) <= 120
        ]
        selected = fresh_candidates[0] if fresh_candidates else candidates[0]
        selected.pop("priority", None)
        if selected["tag"] != candidates[0]["tag"]:
            selected["warning"] = f"preferred tag {candidates[0]['tag']} skipped because latest fact was stale"
        return selected
    warning = "non-USD facts skipped" if saw_non_usd and unit == "USD" else "missing"
    return {"tag": None, "unit": unit, "facts": [], "warning": warning}


def _clean_facts(raw_facts: Any, *, max_points: int, as_of: str | None = None) -> list[dict[str, Any]]:
    rows = []
    if not isinstance(raw_facts, list):
        return rows
    for item in raw_facts:
        if not isinstance(item, dict):
            continue
        if item.get("val") is None or not item.get("end"):
            continue
        form = str(item.get("form") or "")
        if form and form not in PERIODIC_FORMS:
            continue
        if not item.get("frame"):
            continue
        if as_of and not _date_lte(item.get("filed"), as_of):
            continue
        rows.append(
            {
                "end": item.get("end"),
                "filed": item.get("filed"),
                "fy": item.get("fy"),
                "fp": item.get("fp"),
                "form": form,
                "frame": item.get("frame"),
                "val": item.get("val"),
                "accn": item.get("accn"),
            }
        )
    rows.sort(key=lambda row: (row.get("end") or "", row.get("filed") or ""), reverse=True)
    deduped = []
    seen = set()
    for row in rows:
        key = (row.get("end"), row.get("fy"), row.get("fp"), row.get("form"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= max_points:
            break
    return deduped


def _format_metric(metric: str, data: dict[str, Any]) -> str:
    label = metric.replace("_", " ").title()
    facts = data.get("facts") or []
    if not facts:
        reason = data.get("warning") or "missing"
        return f"- {label}: missing ({reason})"
    latest = facts[0]
    changes = []
    qoq_fact, yoy_fact = _comparison_facts(latest, facts)
    qoq = _pct_change(latest.get("val"), qoq_fact.get("val") if qoq_fact else None)
    yoy = _pct_change(latest.get("val"), yoy_fact.get("val") if yoy_fact else None)
    if qoq is not None:
        changes.append(f"QoQ {qoq:+.1f}%")
    if yoy is not None:
        changes.append(f"YoY {yoy:+.1f}%")
    recent = "; ".join(
        f"{fact.get('end')} {fact.get('form')} {fact.get('fp')} frame={fact.get('frame') or 'N/A'} "
        f"accn={fact.get('accn') or 'N/A'}: {_format_value(fact.get('val'), data.get('unit'))}"
        for fact in facts[:4]
    )
    return (
        f"- {label}: latest {latest.get('end')} {latest.get('form')} {latest.get('fp')} "
        f"{_format_value(latest.get('val'), data.get('unit'))}; "
        f"frame={latest.get('frame') or 'N/A'}; accn={latest.get('accn') or 'N/A'}; "
        f"tag={data.get('tag')}; unit={data.get('unit')}; "
        f"{', '.join(changes) if changes else 'trend change unavailable'}; recent: {recent}"
    )


def _fundamental_flags(parsed_facts: dict[str, Any], filings: dict[str, Any], curr_date: str | None) -> list[str]:
    flags = []
    latest_periodic = _latest_periodic_filing(filings)
    if latest_periodic:
        flags.append("recent_filing_available")
        if curr_date and _days_between(latest_periodic.get("filing_date"), curr_date) > 150:
            flags.append("filing_stale")
    else:
        flags.append("filing_stale")
    metrics = parsed_facts.get("metrics") or {}
    revenue = metrics.get("revenue", {}).get("facts") or []
    gross = metrics.get("gross_profit", {}).get("facts") or []
    cash = metrics.get("cash", {}).get("facts") or []
    debt = metrics.get("debt", {}).get("facts") or []
    revenue_yoy = _pct_change(revenue[0].get("val"), revenue[4].get("val")) if len(revenue) > 4 else None
    if revenue_yoy is not None and revenue_yoy > 5:
        flags.append("revenue_acceleration")
    if len(gross) > 1 and len(revenue) > 1:
        try:
            latest_margin = float(gross[0]["val"]) / float(revenue[0]["val"])
            previous_margin = float(gross[1]["val"]) / float(revenue[1]["val"])
            if latest_margin < previous_margin - 0.02:
                flags.append("margin_deterioration")
        except Exception:
            pass
    if cash and debt and float(debt[0].get("val") or 0) > float(cash[0].get("val") or 0) * 2:
        flags.append("cash_debt_risk")
    missing = [name for name, data in metrics.items() if not data.get("facts")]
    if missing:
        flags.append("missing_fields:" + ",".join(missing[:5]))
    stale = [name for name, data in metrics.items() if data.get("stale")]
    if stale:
        flags.append("stale_fields:" + ",".join(stale[:5]))
    return flags


def _compact_confirmation_summary(parsed_facts: dict[str, Any], filings: dict[str, Any], flags: list[str]) -> str:
    revenue = ((parsed_facts.get("metrics") or {}).get("revenue") or {}).get("facts") or []
    latest_revenue = revenue[0] if revenue else None
    latest_periodic = _latest_periodic_filing(filings) or {}
    parts = [
        f"latest_periodic={latest_periodic.get('form')} filed={latest_periodic.get('filing_date')}",
        f"flags={','.join(flags)}",
    ]
    if latest_revenue:
        parts.append(f"revenue={latest_revenue.get('end')} {_format_value(latest_revenue.get('val'), 'USD')}")
    return "; ".join(parts)


def _request_json(url: str, config: dict[str, Any]) -> Any:
    headers = {
        "User-Agent": str(config.get("sec_edgar_user_agent") or DEFAULT_USER_AGENT),
        "Accept-Encoding": "gzip, deflate",
        "Host": re.sub(r"^https?://([^/]+).*$", r"\1", url),
    }
    response = requests.get(url, headers=headers, timeout=float(config.get("sec_edgar_timeout_seconds", 12)))
    response.raise_for_status()
    return response.json()


def _latest_periodic_filing(filings: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [filings.get(form) for form in PERIODIC_FILING_FORMS if filings.get(form)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("filing_date") or ""))


def _latest_period_end(filings: dict[str, Any]) -> str | None:
    filing = _latest_periodic_filing(filings)
    return filing.get("report_date") if filing else None


def _apply_metric_freshness_gate(
    metric: str,
    data: dict[str, Any],
    latest_period_end: str | None,
    stale_days: int,
) -> None:
    facts = data.get("facts") or []
    if not facts or not latest_period_end or stale_days <= 0:
        return
    latest_fact_end = facts[0].get("end")
    age_days = _days_between(latest_fact_end, latest_period_end)
    if age_days <= stale_days:
        return
    data["stale"] = True
    data["stale_latest_fact_end"] = latest_fact_end
    data["stale_latest_period_end"] = latest_period_end
    data["stale_days"] = age_days
    data["stale_facts"] = facts
    data["facts"] = []
    data["warning"] = (
        f"stale: latest SEC {metric} fact {latest_fact_end}, "
        f"latest filing period {latest_period_end}, age {age_days} days"
    )


def _read_cache(key: str, ttl_seconds: int, config: dict[str, Any]) -> Any:
    path = _cache_path(key, config)
    if not path.exists() or ttl_seconds <= 0:
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_cache(key: str, payload: Any, config: dict[str, Any]) -> None:
    path = _cache_path(key, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _cache_path(key: str, config: dict[str, Any]) -> Path:
    cache_dir = Path(config.get("data_cache_dir") or "dataflows/data_cache").expanduser()
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)
    return cache_dir / "sec_edgar" / f"{safe_key}.json"


def _filing_url(cik: str, accession: str | None, document: str | None) -> str | None:
    if not accession or not document:
        return None
    return SEC_ARCHIVES_URL.format(cik_int=int(cik), accession=str(accession).replace("-", ""), document=document)


def _list_get(values: Any, index: int) -> Any:
    return values[index] if isinstance(values, list) and index < len(values) else None


def _format_value(value: Any, unit: str | None) -> str:
    if value is None:
        return "missing"
    try:
        number = float(value)
    except Exception:
        return str(value)
    if unit == "USD":
        abs_number = abs(number)
        if abs_number >= 1_000_000_000:
            return f"${number / 1_000_000_000:.2f}B"
        if abs_number >= 1_000_000:
            return f"${number / 1_000_000:.2f}M"
        return f"${number:,.0f}"
    if unit == "shares":
        if abs(number) >= 1_000_000_000:
            return f"{number / 1_000_000_000:.2f}B shares"
        if abs(number) >= 1_000_000:
            return f"{number / 1_000_000:.2f}M shares"
        return f"{number:,.0f} shares"
    return f"{number:,.0f}"


def _pct_change(current: Any, previous: Any) -> float | None:
    try:
        current_value = float(current)
        previous_value = float(previous)
    except Exception:
        return None
    if previous_value == 0:
        return None
    return ((current_value - previous_value) / abs(previous_value)) * 100.0


def _comparison_facts(latest: dict[str, Any], facts: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    frame = _normalized_frame(latest.get("frame"))
    if not frame:
        return None, None
    quarter_match = re.match(r"^CY(\d{4})Q([1-4])I?$", frame)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter = int(quarter_match.group(2))
        previous_quarter = quarter - 1
        previous_year = year
        if previous_quarter == 0:
            previous_quarter = 4
            previous_year -= 1
        qoq_frame = f"CY{previous_year}Q{previous_quarter}" + ("I" if frame.endswith("I") else "")
        yoy_frame = f"CY{year - 1}Q{quarter}" + ("I" if frame.endswith("I") else "")
        return _find_fact_by_frame(facts, qoq_frame), _find_fact_by_frame(facts, yoy_frame)
    annual_match = re.match(r"^CY(\d{4})$", frame)
    if annual_match:
        yoy_frame = f"CY{int(annual_match.group(1)) - 1}"
        return None, _find_fact_by_frame(facts, yoy_frame)
    return None, None


def _find_fact_by_frame(facts: list[dict[str, Any]], frame: str) -> dict[str, Any] | None:
    target = _normalized_frame(frame)
    return next((fact for fact in facts if _normalized_frame(fact.get("frame")) == target), None)


def _normalized_frame(frame: Any) -> str | None:
    if not frame:
        return None
    return str(frame).upper()


def _days_between(start: str | None, end: str | None) -> int:
    try:
        start_dt = datetime.strptime(str(start), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(str(end), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return max(0, (end_dt - start_dt).days)
    except Exception:
        return 9999


def _date_lte(value: str | None, as_of: str | None) -> bool:
    if not as_of:
        return True
    try:
        value_dt = datetime.strptime(str(value), "%Y-%m-%d").date()
        as_of_dt = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
        return value_dt <= as_of_dt
    except Exception:
        return False


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

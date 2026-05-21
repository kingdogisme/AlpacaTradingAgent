from __future__ import annotations

from pathlib import Path

import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows import sec_edgar_utils as sec


def _config(tmp_path: Path, **overrides):
    return {
        "online_tools": True,
        "sec_edgar_enabled": True,
        "sec_edgar_user_agent": "ATA tests contact@example.com",
        "sec_edgar_timeout_seconds": 3,
        "sec_edgar_cache_ttl_hours": 24,
        "sec_edgar_mapping_cache_ttl_days": 7,
        "sec_edgar_max_quarters": 8,
        "data_cache_dir": str(tmp_path),
        **overrides,
    }


def _companyfacts():
    quarterly_revenue = [
        {"end": "2025-12-31", "filed": "2026-01-31", "fy": 2025, "fp": "Q4", "form": "10-K", "frame": "CY2025Q4", "val": 1200, "accn": "1"},
        {"end": "2025-09-30", "filed": "2025-10-31", "fy": 2025, "fp": "Q3", "form": "10-Q", "frame": "CY2025Q3", "val": 1000, "accn": "2"},
        {"end": "2025-06-30", "filed": "2025-07-31", "fy": 2025, "fp": "Q2", "form": "10-Q", "frame": "CY2025Q2", "val": 900, "accn": "3"},
        {"end": "2025-03-31", "filed": "2025-04-30", "fy": 2025, "fp": "Q1", "form": "10-Q", "frame": "CY2025Q1", "val": 850, "accn": "4"},
        {"end": "2024-12-31", "filed": "2025-01-31", "fy": 2024, "fp": "Q4", "form": "10-K", "frame": "CY2024Q4", "val": 800, "accn": "5"},
    ]
    return {
        "entityName": "Example Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": quarterly_revenue}},
                "GrossProfit": {
                    "units": {
                        "USD": [
                            {**quarterly_revenue[0], "val": 720},
                            {**quarterly_revenue[1], "val": 620},
                        ]
                    }
                },
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{**quarterly_revenue[0], "val": 500}]}},
                "LongTermDebt": {"units": {"USD": [{**quarterly_revenue[0], "val": 700}]}},
                "EntityCommonStockSharesOutstanding": {"units": {"shares": [{**quarterly_revenue[0], "val": 100_000_000}]}},
            }
        },
    }


def _submissions():
    return {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "10-K"],
                "filingDate": ["2026-02-05", "2026-01-31", "2025-02-15"],
                "reportDate": ["2026-02-05", "2025-12-31", "2024-12-31"],
                "accessionNumber": ["0000320193-26-000003", "0000320193-26-000002", "0000320193-25-000001"],
                "primaryDocument": ["a8k.htm", "a10q.htm", "a10k.htm"],
            }
        }
    }


def test_resolve_cik_uses_padded_cik_and_cache(monkeypatch, tmp_path):
    calls = []

    def fake_request(url, config):
        calls.append(url)
        return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

    monkeypatch.setattr(sec, "_request_json", fake_request)
    cfg = _config(tmp_path)

    assert sec.resolve_cik("aapl", cfg)[0] == "0000320193"
    assert sec.resolve_cik("AAPL", cfg)[0] == "0000320193"
    assert calls == [sec.SEC_TICKERS_URL]


def test_companyfacts_parser_selects_revenue_tag_by_priority(tmp_path):
    parsed = sec.parse_companyfacts(_companyfacts(), max_points=8)

    revenue = parsed["metrics"]["revenue"]
    assert revenue["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue["facts"][0]["end"] == "2025-12-31"
    assert parsed["metrics"]["operating_income"]["warning"] == "missing"


def test_companyfacts_parser_skips_stale_preferred_tag():
    payload = _companyfacts()
    payload["facts"]["us-gaap"]["Revenues"] = {
        "units": {
            "USD": [
                {
                    "end": "2018-06-30",
                    "filed": "2018-07-31",
                    "fy": 2018,
                    "fp": "Q2",
                    "form": "10-Q",
                    "frame": "CY2018Q2",
                    "val": 100,
                }
            ]
        }
    }

    parsed = sec.parse_companyfacts(payload, max_points=8)

    revenue = parsed["metrics"]["revenue"]
    assert revenue["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue["facts"][0]["end"] == "2025-12-31"
    assert "preferred tag Revenues skipped" in revenue["warning"]


def test_non_usd_facts_are_skipped_with_warning():
    parsed = sec.parse_companyfacts(
        {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "EUR": [
                                {"end": "2025-12-31", "filed": "2026-01-31", "form": "10-K", "val": 100}
                            ]
                        }
                    }
                }
            }
        }
    )

    assert parsed["metrics"]["revenue"]["warning"] == "non-USD facts skipped"


def test_format_sec_report_is_compact_and_includes_sources(tmp_path):
    cik = "0000320193"
    filings = sec.latest_filings(_submissions(), cik)
    parsed = sec.parse_companyfacts(_companyfacts(), max_points=8)

    report = sec.format_sec_report(
        ticker="AAPL",
        curr_date="2026-02-10",
        cik=cik,
        identity={"title": "Apple Inc."},
        filings=filings,
        parsed_facts=parsed,
    )

    assert "SEC EDGAR Official Fundamentals for AAPL" in report
    assert "CIK: 0000320193" in report
    assert "10-Q: filed 2026-01-31" in report
    assert "accession 0000320193-26-000002" in report
    assert "tag=RevenueFromContractWithCustomerExcludingAssessedTax" in report
    assert "Operating Income: missing" in report
    assert "YoY +50.0%" in report


def test_latest_filings_respects_as_of_date():
    filings = sec.latest_filings(_submissions(), "0000320193", as_of="2025-12-01")

    assert filings["10-K"]["filing_date"] == "2025-02-15"
    assert filings["10-Q"] is None
    assert filings["8-K"] is None


def test_companyfacts_parser_filters_facts_after_as_of_date():
    parsed = sec.parse_companyfacts(_companyfacts(), max_points=8, as_of="2025-08-15")

    revenue = parsed["metrics"]["revenue"]
    assert revenue["facts"][0]["end"] == "2025-06-30"
    assert all(fact["filed"] <= "2025-08-15" for fact in revenue["facts"])
    assert "2025-12-31" not in {fact["end"] for fact in revenue["facts"]}


def test_metric_freshness_gate_hides_stale_values():
    payload = _companyfacts()
    payload["facts"]["us-gaap"]["NetIncomeLoss"] = {
        "units": {
            "USD": [
                {
                    "end": "2021-12-31",
                    "filed": "2022-02-01",
                    "fy": 2021,
                    "fp": "FY",
                    "form": "10-K",
                    "frame": "CY2021",
                    "val": 42,
                    "accn": "old",
                }
            ]
        }
    }

    parsed = sec.parse_companyfacts(
        payload,
        max_points=8,
        latest_period_end="2025-12-31",
        stale_days=540,
    )

    net_income = parsed["metrics"]["net_income"]
    assert net_income["facts"] == []
    assert net_income["stale"] is True
    assert "latest SEC net_income fact 2021-12-31" in net_income["warning"]


def test_stale_metrics_are_reported_as_missing_not_values():
    payload = _companyfacts()
    payload["facts"]["us-gaap"]["NetIncomeLoss"] = {
        "units": {
            "USD": [
                {
                    "end": "2021-12-31",
                    "filed": "2022-02-01",
                    "fy": 2021,
                    "fp": "FY",
                    "form": "10-K",
                    "frame": "CY2021",
                    "val": 42,
                    "accn": "old",
                }
            ]
        }
    }
    filings = sec.latest_filings(_submissions(), "0000320193")
    parsed = sec.parse_companyfacts(
        payload,
        max_points=8,
        latest_period_end="2025-12-31",
        stale_days=540,
    )

    report = sec.format_sec_report(
        ticker="AAPL",
        curr_date="2026-02-10",
        cik="0000320193",
        identity={"title": "Apple Inc."},
        filings=filings,
        parsed_facts=parsed,
    )

    assert "Net Income: missing (stale: latest SEC net_income fact 2021-12-31" in report
    assert "$42" not in report


def test_request_json_sends_user_agent(monkeypatch, tmp_path):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_get(url, headers, timeout):
        captured["headers"] = headers
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(sec.requests, "get", fake_get)

    payload = sec._request_json("https://data.sec.gov/submissions/CIK0000320193.json", _config(tmp_path))

    assert payload == {"ok": True}
    assert captured["headers"]["User-Agent"] == "ATA tests contact@example.com"
    assert captured["timeout"] == 3


def test_get_sec_edgar_fundamentals_unavailable_is_graceful(tmp_path):
    report = sec.get_sec_edgar_fundamentals(
        "NOW",
        "2026-02-10",
        _config(tmp_path, online_tools=False),
    )

    assert "unavailable" in report
    assert "disabled" in report


def test_interface_delegates_to_sec_report(monkeypatch):
    captured = {}

    def fake_report(ticker, curr_date, config):
        captured["ticker"] = ticker
        captured["curr_date"] = curr_date
        captured["config"] = config
        return "SEC report"

    monkeypatch.setattr(interface, "get_sec_edgar_fundamentals_report", fake_report)

    assert interface.get_sec_edgar_fundamentals("NOW", "2026-02-10") == "SEC report"
    assert captured["ticker"] == "NOW"

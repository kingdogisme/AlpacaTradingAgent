from __future__ import annotations

import json

import cli.main as cli_main
from typer.testing import CliRunner

import tradingagents.portfolio.context as portfolio_context
import tradingagents.portfolio.service as portfolio_service
import tradingagents.research as research_module
from cli.main import app
from tradingagents.contracts import InvestmentDecision, PortfolioContext, ResearchReport, ResearchRequest
from tradingagents.research import ResearchRunResult


def test_ata_report_returns_research_report_without_plan_persistence(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", str(tmp_path))

    class FakeResearchService:
        def __init__(self, config):
            captured["config"] = config

        def run(self, request: ResearchRequest) -> ResearchRunResult:
            captured["request"] = request
            report = ResearchReport(
                request_id=request.request_id,
                symbol=request.symbol,
                trade_date=request.trade_date,
                horizon=request.horizon,
                thesis=request.thesis or "NVDA thesis",
                conclusion="B",
                confidence="medium",
                audit_refs={"run_id": "run-v2"},
            )
            return ResearchRunResult(
                request=request,
                report=report,
                legacy_state={"final_trade_decision": "legacy text"},
                final_signal="BUY",
                run_id="run-v2",
                audit_path="/tmp/run-v2.json",
            )

    monkeypatch.setattr(research_module, "ResearchService", FakeResearchService)

    result = CliRunner().invoke(
        app,
        [
            "ata-report",
            "--ticker",
            "nvda",
            "--trade-date",
            "2026-06-06",
            "--horizon",
            "position",
            "--analysts",
            "market,news",
            "--thesis",
            "AI capex remains resilient",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    request = captured["request"]
    assert isinstance(request, ResearchRequest)
    assert request.symbol == "NVDA"
    assert request.selected_analysts == ["market", "news"]
    assert payload["kind"] == "ata_report"
    assert payload["payload"]["report_id"].startswith("rpt_")
    assert payload["payload"]["report_path"].endswith(f"{payload['payload']['report_id']}.json")
    assert payload["payload"]["research_report"]["schema_version"] == "v2"
    assert payload["payload"]["run_id"] == "run-v2"
    assert "plan_id" not in payload["payload"]
    assert (tmp_path / "ata_v2" / "reports" / f"{payload['payload']['report_id']}.json").exists()


def test_ata_decide_loads_report_and_returns_investment_decision(tmp_path, monkeypatch):
    report = ResearchReport(
        request_id="rrq-1",
        report_id="rpt-1",
        symbol="AAPL",
        trade_date="2026-06-06",
        horizon="position",
        thesis="AAPL thesis",
        conclusion="B",
        confidence="medium",
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_build_portfolio_context(symbol: str, config=None):
        captured["symbol"] = symbol
        captured["config"] = config
        return PortfolioContext(account_snapshot={"buying_power": 50000})

    class FakePortfolioDecisionService:
        def __init__(self, config):
            captured["service_config"] = config

        def decide(self, loaded_report: ResearchReport, context: PortfolioContext) -> InvestmentDecision:
            captured["report"] = loaded_report
            captured["context"] = context
            return InvestmentDecision(
                decision_id="dec-1",
                report_id=loaded_report.report_id,
                symbol=loaded_report.symbol,
                human_action="BUY",
                actionability="conditional",
                confidence=loaded_report.confidence,
                invalidation={"price_below": 100.0},
                alpaca_intent="CONDITIONAL_ORDER",
                conditional_trade_plan={"plan_id": "plan-1", "symbol": loaded_report.symbol},
            )

    monkeypatch.setattr(portfolio_context, "build_portfolio_context", fake_build_portfolio_context)
    monkeypatch.setattr(portfolio_service, "PortfolioDecisionService", FakePortfolioDecisionService)

    result = CliRunner().invoke(app, ["ata-decide", "--report-json", str(report_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert captured["symbol"] == "AAPL"
    assert captured["report"].report_id == "rpt-1"
    assert payload["kind"] == "ata_decide"
    assert payload["payload"]["decision_id"] == "dec-1"
    assert payload["payload"]["decision_path"].endswith("dec-1.json")
    assert payload["payload"]["alpaca_intent"] == "CONDITIONAL_ORDER"
    assert payload["payload"]["plan_id"] == "plan-1"
    assert payload["payload"]["investment_decision"]["schema_version"] == "v2"


def test_ata_decide_can_load_report_by_stored_report_id(tmp_path, monkeypatch):
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", str(tmp_path))
    report = ResearchReport(
        request_id="rrq-1",
        report_id="rpt-stored",
        symbol="MSFT",
        trade_date="2026-06-06",
        horizon="position",
        thesis="MSFT thesis",
        conclusion="B",
        confidence="medium",
    )
    report_dir = tmp_path / "ata_v2" / "reports"
    report_dir.mkdir(parents=True)
    (report_dir / "rpt-stored.json").write_text(report.model_dump_json(), encoding="utf-8")

    def fake_build_portfolio_context(symbol: str, config=None):
        return PortfolioContext(account_snapshot={"buying_power": 50000})

    class FakePortfolioDecisionService:
        def __init__(self, config):
            self.config = config

        def decide(self, loaded_report: ResearchReport, context: PortfolioContext) -> InvestmentDecision:
            return InvestmentDecision(
                decision_id="dec-stored",
                report_id=loaded_report.report_id,
                symbol=loaded_report.symbol,
                human_action="BUY",
                actionability="conditional",
                confidence=loaded_report.confidence,
                invalidation={"price_below": 100.0},
                alpaca_intent="CONDITIONAL_ORDER",
                conditional_trade_plan={"plan_id": "plan-stored", "symbol": loaded_report.symbol},
            )

    monkeypatch.setattr(portfolio_context, "build_portfolio_context", fake_build_portfolio_context)
    monkeypatch.setattr(portfolio_service, "PortfolioDecisionService", FakePortfolioDecisionService)

    result = CliRunner().invoke(app, ["ata-decide", "--report-id", "rpt-stored"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)["payload"]
    assert payload["report_path"].endswith("rpt-stored.json")
    assert payload["decision_path"].endswith("dec-stored.json")
    assert (tmp_path / "ata_v2" / "decisions" / "dec-stored.json").exists()


def test_ata_run_defaults_to_v2_report_and_decision(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", str(tmp_path))

    class FakeResearchService:
        def __init__(self, config):
            captured["research_config"] = config

        def run(self, request: ResearchRequest) -> ResearchRunResult:
            captured["request"] = request
            report = ResearchReport(
                request_id=request.request_id,
                report_id="rpt-ata-run",
                symbol=request.symbol,
                trade_date=request.trade_date,
                horizon=request.horizon,
                thesis="NVDA thesis",
                conclusion="B",
                confidence="medium",
                audit_refs={"run_id": "run-v2"},
            )
            return ResearchRunResult(
                request=request,
                report=report,
                final_signal="BUY",
                run_id="run-v2",
                audit_path="/tmp/run-v2.json",
            )

    class FakePortfolioDecisionService:
        def __init__(self, config):
            captured["decision_config"] = config

        def decide(self, loaded_report: ResearchReport, context: PortfolioContext) -> InvestmentDecision:
            captured["report"] = loaded_report
            captured["context"] = context
            return InvestmentDecision(
                decision_id="dec-ata-run",
                report_id=loaded_report.report_id,
                symbol=loaded_report.symbol,
                human_action="BUY",
                actionability="conditional",
                confidence=loaded_report.confidence,
                invalidation={"price_below": 100.0},
                alpaca_intent="CONDITIONAL_ORDER",
                conditional_trade_plan={"plan_id": "plan-ata-run", "symbol": loaded_report.symbol},
            )

    def fake_build_portfolio_context(symbol: str, config=None):
        captured["context_symbol"] = symbol
        return PortfolioContext(account_snapshot={"buying_power": 50000})

    monkeypatch.setattr(research_module, "ResearchService", FakeResearchService)
    monkeypatch.setattr(portfolio_service, "PortfolioDecisionService", FakePortfolioDecisionService)
    monkeypatch.setattr(portfolio_context, "build_portfolio_context", fake_build_portfolio_context)

    result = CliRunner().invoke(
        app,
        [
            "ata-run",
            "nvda",
            "--trade-date",
            "2026-06-06",
            "--horizon",
            "position",
            "--analysts",
            "market,news",
            "--no-record-ad-handoff",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["kind"] == "ata_run"
    assert payload["payload"]["mode"] == "v2_report_decision"
    assert payload["payload"]["report_id"] == "rpt-ata-run"
    assert payload["payload"]["report_path"].endswith("rpt-ata-run.json")
    assert payload["payload"]["decision_id"] == "dec-ata-run"
    assert payload["payload"]["decision_path"].endswith("dec-ata-run.json")
    assert payload["payload"]["alpaca_intent"] == "CONDITIONAL_ORDER"
    assert payload["payload"]["plan_id"] == "plan-ata-run"
    assert captured["request"].selected_analysts == ["market", "news"]

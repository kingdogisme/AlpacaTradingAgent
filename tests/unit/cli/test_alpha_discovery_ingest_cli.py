from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app
from tradingagents.trade_lifecycle import ConditionalTradePlan, MarketObservation, TradePlanRepository


runner = CliRunner()


def test_ad_ingest_cli_accepts_candidate_file(tmp_path, monkeypatch):
    db_path = tmp_path / "ad.sqlite"
    payload_path = tmp_path / "candidates.json"
    payload_path.write_text(
        json.dumps(
            [
                {
                    "ticker": "AMD",
                    "headline": "Inference server demand rising",
                    "theme": "AI compute",
                    "alpha_score": 0.73,
                    "tier": "B",
                    "article_url": "https://example.com/amd",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_ALPHA_DISCOVERY_DB_PATH", str(db_path))
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "alpha_discovery_db_path", str(db_path))

    result = runner.invoke(app, ["ad-ingest", "--file", str(payload_path), "--source", "n8n_watchlist"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["kind"] == "ad_ingest"
    assert data["payload"]["accepted"] == 1
    assert data["payload"]["tickers"] == ["AMD"]


def test_alpha_discovery_cli_black_box_lifecycle(tmp_path, monkeypatch):
    db_path = tmp_path / "ad.sqlite"
    payload_path = tmp_path / "candidates.json"
    payload_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "AMD",
                        "headline": "Inference server demand rising",
                        "theme": "AI compute",
                        "catalyst": "hyperscaler accelerator refresh",
                        "alpha_score": 0.74,
                        "tier": "B",
                        "article_url": "https://example.com/amd",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_ALPHA_DISCOVERY_DB_PATH", str(db_path))
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "alpha_discovery_db_path", str(db_path))

    ingest = runner.invoke(app, ["ad-ingest", "--file", str(payload_path), "--source", "n8n_watchlist"])
    basket = runner.invoke(app, ["basket-list", "--tier", "B", "--status", "open", "--limit", "5"])
    events = runner.invoke(app, ["ad-events", "--limit", "20"])
    health = runner.invoke(app, ["ad-health"])
    cron_run = runner.invoke(app, ["cron-run", "--tier", "B", "--max-symbols", "1"])

    assert ingest.exit_code == 0
    assert basket.exit_code == 0
    assert events.exit_code == 0
    assert health.exit_code == 0
    assert cron_run.exit_code == 0

    basket_payload = json.loads(basket.stdout)["payload"]
    event_payload = json.loads(events.stdout)["payload"]
    health_payload = json.loads(health.stdout)["payload"]
    cron_payload = json.loads(cron_run.stdout)["payload"]

    assert basket_payload[0]["ticker"] == "AMD"
    assert any(event["event_type"] == "external_ingest_start" for event in event_payload)
    assert health_payload["status"] in {"ok", "degraded"}
    assert cron_payload["execute"] is False
    assert cron_payload["run_status_counts"] == {"dry_run": 1}


def test_cron_run_a_list_auto_executes_unless_dry_run(tmp_path, monkeypatch):
    db_path = tmp_path / "ad.sqlite"
    payload_path = tmp_path / "candidates.json"
    payload_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "AMD",
                        "headline": "Inference server demand rising",
                        "alpha_score": 0.9,
                        "tier": "A",
                        "article_url": "https://example.com/amd",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_ALPHA_DISCOVERY_DB_PATH", str(db_path))
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "alpha_discovery_db_path", str(db_path))

    class FakeV2Runner:
        def __init__(self, config):
            self.config = config

        def run(self, ticker, trade_date, analysts, config_overrides=None):
            assert ticker == "AMD"
            assert analysts == ["market", "fundamentals", "news", "social", "macro"]
            assert config_overrides["trading_horizon"] == "position"
            assert config_overrides["trading_mode"] == "investment"
            assert config_overrides["episode_ledger_metadata"]["source"] == "alpha_discovery"
            return "run-1", "BUY", "high"

    monkeypatch.setattr(cli_main, "_AtaV2Runner", FakeV2Runner)

    ingest = runner.invoke(app, ["ad-ingest", "--file", str(payload_path), "--source", "n8n_watchlist"])
    cron_run = runner.invoke(app, ["cron-run", "--tier", "A", "--max-symbols", "1"])
    dry_run = runner.invoke(app, ["cron-run", "--tier", "A", "--max-symbols", "1", "--dry-run"])

    assert ingest.exit_code == 0
    assert cron_run.exit_code == 0
    assert dry_run.exit_code == 0

    cron_payload = json.loads(cron_run.stdout)["payload"]
    dry_payload = json.loads(dry_run.stdout)["payload"]

    assert cron_payload["execute"] is True
    assert cron_payload["runner"] == "ata_v2"
    assert cron_payload["run_status_counts"] == {"executed": 1}
    assert dry_payload["execute"] is False
    assert dry_payload["runner"] == "ata_v2"


def test_cron_run_legacy_graph_flag_uses_legacy_runner(tmp_path, monkeypatch):
    db_path = tmp_path / "ad.sqlite"
    payload_path = tmp_path / "candidates.json"
    payload_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "AMD",
                        "headline": "Inference server demand rising",
                        "alpha_score": 0.9,
                        "tier": "A",
                        "article_url": "https://example.com/amd",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_ALPHA_DISCOVERY_DB_PATH", str(db_path))
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "alpha_discovery_db_path", str(db_path))

    used = {"legacy": False}

    class FakeGraphRunner:
        def __init__(self, config):
            self.config = config

        def run(self, ticker, trade_date, analysts, config_overrides=None):
            used["legacy"] = True
            return "run-legacy", "BUY", "medium", "plan-legacy"

    class FailV2Runner:
        def __init__(self, config):
            self.config = config

        def run(self, *args, **kwargs):
            raise AssertionError("cron-run --legacy-graph must not use V2 runner")

    monkeypatch.setattr(cli_main, "_TradingAgentsGraphRunner", FakeGraphRunner)
    monkeypatch.setattr(cli_main, "_AtaV2Runner", FailV2Runner)

    ingest = runner.invoke(app, ["ad-ingest", "--file", str(payload_path), "--source", "n8n_watchlist"])
    cron_run = runner.invoke(app, ["cron-run", "--tier", "A", "--max-symbols", "1", "--legacy-graph"])

    assert ingest.exit_code == 0
    assert cron_run.exit_code == 0
    assert used["legacy"] is True
    cron_payload = json.loads(cron_run.stdout)["payload"]
    assert cron_payload["runner"] == "legacy_graph"
    assert cron_payload["run_status_counts"] == {"executed": 1}


def _future(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _plan(**overrides):
    payload = {
        "symbol": "AAPL",
        "action": "BUY",
        "trigger": {"type": "market"},
        "invalidation": {"price_below": 95.0},
        "valid_until": _future(),
        "max_notional": 500.0,
        "risk_budget": {"max_notional": 500.0, "max_gap_pct": 0.08, "min_volume_ratio": 0.2},
        "execution_policy": {"notional": 500.0, "paper_only": True},
    }
    payload.update(overrides)
    return ConditionalTradePlan(**payload)


def test_trade_monitor_cli_once_triggers_and_trade_plan_cli_reports(tmp_path):
    db_path = tmp_path / "trade.sqlite"
    repo = TradePlanRepository(db_path)
    plan = _plan()
    repo.upsert_plan(plan)

    with patch("tradingagents.trade_lifecycle.monitor.TradeMonitorService._observe") as observe, patch(
        "tradingagents.trade_lifecycle.monitor.TradeMonitorService._account_info",
        return_value={"equity": 10000, "buying_power": 10000},
    ), patch(
        "tradingagents.trade_lifecycle.monitor.TradeMonitorService._current_position",
        return_value="NEUTRAL",
    ), patch(
        "tradingagents.trade_lifecycle.monitor.TradeMonitorService._execute_plan",
        return_value={"success": True, "actions": [{"action": "buy"}]},
    ):
        observe.return_value = __import__("tradingagents.trade_lifecycle", fromlist=["MarketObservation"]).MarketObservation(
            symbol="AAPL",
            price=100.0,
            prev_close=99.0,
            gap_pct=0.01,
            volume_ratio=1.0,
        )
        monitor = runner.invoke(app, ["trade-monitor", "--once", "--symbol", "AAPL", "--db-path", str(db_path)])

    plan_list = runner.invoke(app, ["trade-plan-list", "--status", "needs_review", "--db-path", str(db_path)])
    plan_show = runner.invoke(app, ["trade-plan-show", "--plan-id", plan.plan_id, "--db-path", str(db_path)])
    health = runner.invoke(app, ["trade-plan-health", "--db-path", str(db_path)])

    assert monitor.exit_code == 0
    assert plan_list.exit_code == 0
    assert plan_show.exit_code == 0
    assert health.exit_code == 0
    monitor_payload = json.loads(monitor.stdout)["payload"]
    list_payload = json.loads(plan_list.stdout)["payload"]
    show_payload = json.loads(plan_show.stdout)["payload"]
    health_payload = json.loads(health.stdout)["payload"]
    assert monitor_payload["processed"][0]["decision"] == "needs_review"
    assert list_payload[0]["status"] == "needs_review"
    assert show_payload["status"] == "needs_review"
    assert health_payload["counts_by_status"]["needs_review"] == 1


def test_trade_plan_execute_cli_routes_reviewed_plan_to_broker(tmp_path, monkeypatch):
    db_path = tmp_path / "trade.sqlite"
    repo = TradePlanRepository(db_path)
    plan = _plan()
    repo.upsert_plan(plan)
    repo.update_status(
        plan.plan_id,
        "needs_review",
        reason="trigger met",
        payload={
            "observation": MarketObservation(
                symbol="AAPL",
                price=100.0,
                gap_pct=0.01,
                volume_ratio=1.0,
            ).model_dump(mode="json")
        },
    )

    class FakeBroker:
        def get_account_snapshot(self, **kwargs):
            return {"equity": 10000, "buying_power": 10000, "broker_args": kwargs}

        def get_current_position(self, symbol, **kwargs):
            return "NEUTRAL"

        def execute_trading_action(self, **kwargs):
            return {"success": True, "dry_run": True, "broker": "fake", "order_request": kwargs}

    class FakeRouter:
        def __init__(self, *_args, **_kwargs):
            self.broker = FakeBroker()

        def get_account_snapshot(self, **kwargs):
            return self.broker.get_account_snapshot(**kwargs)

        def get_current_position(self, *args, **kwargs):
            return self.broker.get_current_position(*args, **kwargs)

        def resolve_broker_name(self, **_kwargs):
            return "robinhood"

        def execute_trading_action(self, **kwargs):
            return self.broker.execute_trading_action(**kwargs)

    monkeypatch.setattr("tradingagents.execution.plan_executor.create_broker_router", lambda _config: FakeRouter())

    result = runner.invoke(
        app,
        [
            "trade-plan-execute",
            "--plan-id",
            plan.plan_id,
            "--broker",
            "robinhood",
            "--dry-run",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["execution"]["status"] == "needs_review"
    assert payload["execution"]["broker_response"]["order_request"]["broker_name"] == "robinhood"
    assert payload["plan"]["status"] == "needs_review"
    assert any(event["event_type"] == "broker_review" for event in repo.list_events(plan.plan_id))


def test_trade_monitor_cli_untriggered_and_expired_outputs(tmp_path):
    db_path = tmp_path / "trade.sqlite"
    repo = TradePlanRepository(db_path)
    waiting = _plan(trigger={"type": "price_above", "price_above": 110.0})
    expired = _plan(symbol="MSFT", valid_until=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    repo.upsert_plan(waiting)
    repo.upsert_plan(expired)

    with patch("tradingagents.trade_lifecycle.monitor.TradeMonitorService._observe") as observe:
        observe.return_value = __import__("tradingagents.trade_lifecycle", fromlist=["MarketObservation"]).MarketObservation(
            symbol="AAPL",
            price=100.0,
        )
        result = runner.invoke(app, ["trade-monitor", "--once", "--db-path", str(db_path)])

    payload = json.loads(result.stdout)["payload"]
    assert result.exit_code == 0
    assert payload["processed"][0]["decision"] == "waiting"
    assert expired.plan_id in payload["expired"]


def test_trade_monitor_cli_live_account_rejects_without_order(tmp_path):
    db_path = tmp_path / "trade.sqlite"
    repo = TradePlanRepository(db_path)
    plan = _plan()
    repo.upsert_plan(plan)
    cli_main.DEFAULT_CONFIG["alpaca_use_paper"] = False

    with patch("tradingagents.trade_lifecycle.monitor.TradeMonitorService._observe") as observe, patch(
        "tradingagents.trade_lifecycle.monitor.TradeMonitorService._account_info",
        return_value={"equity": 10000, "buying_power": 10000},
    ), patch(
        "tradingagents.trade_lifecycle.monitor.TradeMonitorService._current_position",
        return_value="NEUTRAL",
    ), patch("tradingagents.trade_lifecycle.monitor.TradeMonitorService._execute_plan") as execute:
        observe.return_value = __import__("tradingagents.trade_lifecycle", fromlist=["MarketObservation"]).MarketObservation(
            symbol="AAPL",
            price=100.0,
        )
        result = runner.invoke(app, ["trade-monitor", "--once", "--symbol", "AAPL", "--db-path", str(db_path)])

    payload = json.loads(result.stdout)["payload"]
    assert result.exit_code == 0
    assert payload["processed"][0]["decision"] == "needs_review"
    assert any("manual review" in reason for reason in payload["processed"][0]["reasons"])
    execute.assert_not_called()

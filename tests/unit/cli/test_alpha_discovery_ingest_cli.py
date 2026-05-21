from __future__ import annotations

import json

from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app


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

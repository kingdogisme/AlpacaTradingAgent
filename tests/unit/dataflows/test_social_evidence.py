from __future__ import annotations

import json
from io import BytesIO
from urllib.error import URLError

from tradingagents.dataflows import social_evidence


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_grounded_social_evidence_degrades_when_public_apis_fail(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(social_evidence, "urlopen", fail_urlopen)

    block = social_evidence.build_grounded_social_evidence("AAPL", "2026-01-02")

    assert "Grounded social/news evidence block" in block
    assert "Source: StockTwits" in block
    assert "Source: Reddit public JSON" in block
    assert "Sample count: 0" in block
    assert "unavailable" in block


def test_stocktwits_evidence_formats_source_timestamp_and_sample_count(monkeypatch):
    payload = {
        "messages": [
            {
                "created_at": "2026-01-02T15:00:00Z",
                "body": "AAPL setup looks strong",
                "user": {"username": "trader1"},
                "entities": {"sentiment": {"basic": "Bullish"}},
            }
        ]
    }
    monkeypatch.setattr(social_evidence, "urlopen", lambda *_args, **_kwargs: _Response(payload))

    block = social_evidence.fetch_stocktwits_evidence("AAPL", limit=1)

    assert "Source: StockTwits public symbol stream" in block
    assert "Timestamp:" in block
    assert "Sample count: 1" in block
    assert "bullish=1" in block
    assert "AAPL setup looks strong" in block


def test_reddit_evidence_formats_public_json_samples(monkeypatch):
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "created_utc": 1767375600,
                        "title": "AAPL discussion",
                        "selftext": "earnings setup",
                        "score": 12,
                        "num_comments": 4,
                    }
                }
            ]
        }
    }
    monkeypatch.setattr(social_evidence, "urlopen", lambda *_args, **_kwargs: _Response(payload))

    block = social_evidence.fetch_reddit_public_evidence("AAPL", subreddits=("stocks",), limit_per_subreddit=1)

    assert "Source: Reddit public JSON search" in block
    assert "Timestamp:" in block
    assert "Sample count: 1" in block
    assert "r/stocks: sample_count=1" in block
    assert "AAPL discussion" in block

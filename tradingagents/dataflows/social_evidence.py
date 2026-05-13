from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tradingagents.dataflows.ticker_utils import TickerUtils

logger = logging.getLogger(__name__)

_USER_AGENT = "AlpacaTradingAgent/0.1 (+https://github.com/IvanWng97/AlpacaTradingAgent)"
_STOCKTWITS_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_REDDIT_API = "https://www.reddit.com/r/{subreddit}/search.json?{query}"
_DEFAULT_REDDIT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


def build_grounded_social_evidence(
    ticker: str,
    trade_date: str,
    *,
    enabled: bool = True,
    stocktwits_limit: int = 12,
    reddit_limit_per_subreddit: int = 3,
    timeout: float = 6.0,
    reddit_subreddits: Iterable[str] = _DEFAULT_REDDIT_SUBREDDITS,
) -> str:
    """Build a prompt-ready social evidence block that never raises."""
    if not enabled:
        return ""

    captured_at = datetime.now(timezone.utc).isoformat()
    stocktwits = fetch_stocktwits_evidence(
        ticker,
        limit=stocktwits_limit,
        timeout=timeout,
    )
    reddit = fetch_reddit_public_evidence(
        ticker,
        limit_per_subreddit=reddit_limit_per_subreddit,
        timeout=timeout,
        subreddits=reddit_subreddits,
    )
    return "\n".join(
        [
            "Grounded social/news evidence block:",
            f"- Ticker: {ticker}",
            f"- Trade date: {trade_date}",
            f"- Captured at: {captured_at}",
            "- Source policy: Use these source-labeled samples as evidence. "
            "If samples are unavailable or sparse, say so explicitly and do not invent sentiment.",
            "",
            stocktwits,
            "",
            reddit,
        ]
    ).strip()


def fetch_stocktwits_evidence(ticker: str, *, limit: int = 12, timeout: float = 6.0) -> str:
    symbol = _stocktwits_symbol(ticker)
    if not symbol:
        return _empty_block("StockTwits", "unsupported ticker format", ticker)

    url = _STOCKTWITS_API.format(ticker=symbol)
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.info("StockTwits evidence unavailable for %s: %s", ticker, exc)
        return _empty_block("StockTwits", type(exc).__name__, ticker)

    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    if not messages:
        return _empty_block("StockTwits", "no samples", ticker)

    samples: list[str] = []
    bullish = bearish = unlabeled = 0
    for message in messages[: max(0, limit)]:
        if not isinstance(message, dict):
            continue
        sentiment = _stocktwits_sentiment(message)
        if sentiment == "Bullish":
            bullish += 1
        elif sentiment == "Bearish":
            bearish += 1
        else:
            unlabeled += 1
            sentiment = "Unlabeled"
        created = str(message.get("created_at") or "unknown")
        user = ((message.get("user") or {}).get("username") or "unknown").strip()
        body = _compact_text(message.get("body"), 240)
        samples.append(f"- [{created}] @{user} sentiment={sentiment}: {body}")

    count = len(samples)
    if count == 0:
        return _empty_block("StockTwits", "no parseable samples", ticker)
    summary = (
        f"Source: StockTwits public symbol stream\n"
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        f"Sample count: {count}\n"
        f"Sentiment labels: bullish={bullish}, bearish={bearish}, unlabeled={unlabeled}"
    )
    return summary + "\n" + "\n".join(samples)


def fetch_reddit_public_evidence(
    ticker: str,
    *,
    limit_per_subreddit: int = 3,
    timeout: float = 6.0,
    subreddits: Iterable[str] = _DEFAULT_REDDIT_SUBREDDITS,
    inter_request_delay: float = 0.0,
) -> str:
    query_symbol = _reddit_query_symbol(ticker)
    blocks: list[str] = []
    total = 0
    for index, subreddit in enumerate(subreddits):
        if index > 0 and inter_request_delay > 0:
            time.sleep(inter_request_delay)
        posts = _fetch_reddit_subreddit(
            query_symbol,
            subreddit,
            limit=max(0, limit_per_subreddit),
            timeout=timeout,
        )
        total += len(posts)
        if not posts:
            blocks.append(f"r/{subreddit}: sample_count=0")
            continue
        lines = [f"r/{subreddit}: sample_count={len(posts)}"]
        for post in posts:
            title = _compact_text(post.get("title"), 180)
            created = post.get("created_utc")
            created_text = (
                datetime.fromtimestamp(float(created), timezone.utc).date().isoformat()
                if created
                else "unknown"
            )
            score = post.get("score", 0)
            comments = post.get("num_comments", 0)
            excerpt = _compact_text(post.get("selftext"), 180)
            suffix = f" excerpt={excerpt}" if excerpt else ""
            lines.append(f"- [{created_text}] score={score} comments={comments}: {title}{suffix}")
        blocks.append("\n".join(lines))

    if total == 0:
        return _empty_block("Reddit public JSON", "no samples", ticker)
    return (
        "Source: Reddit public JSON search\n"
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        f"Sample count: {total}\n"
        + "\n\n".join(blocks)
    )


def _fetch_reddit_subreddit(
    query_symbol: str,
    subreddit: str,
    *,
    limit: int,
    timeout: float,
) -> list[dict]:
    query = urlencode(
        {
            "q": query_symbol,
            "restrict_sr": "on",
            "sort": "new",
            "t": "week",
            "limit": limit,
        }
    )
    url = _REDDIT_API.format(subreddit=subreddit, query=query)
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.info("Reddit evidence unavailable for r/%s %s: %s", subreddit, query_symbol, exc)
        return []
    children = ((payload.get("data") or {}).get("children") or []) if isinstance(payload, dict) else []
    return [item.get("data", {}) for item in children if isinstance(item, dict)]


def _stocktwits_symbol(ticker: str) -> str:
    try:
        info = TickerUtils.standardize_ticker(ticker)
        return info["clean_symbol"]
    except Exception:
        return str(ticker or "").strip().upper().replace("/", "").replace("-", "")


def _reddit_query_symbol(ticker: str) -> str:
    try:
        info = TickerUtils.standardize_ticker(ticker)
        return info["clean_symbol"]
    except Exception:
        return str(ticker or "").strip().upper().replace("/", " ").replace("-", " ")


def _stocktwits_sentiment(message: dict) -> str | None:
    sentiment = ((message.get("entities") or {}).get("sentiment") or {})
    return sentiment.get("basic") if isinstance(sentiment, dict) else None


def _compact_text(value, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    return text[: max_chars - 3] + "..." if len(text) > max_chars else text


def _empty_block(source: str, reason: str, ticker: str) -> str:
    return (
        f"Source: {source}\n"
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        "Sample count: 0\n"
        f"Status: unavailable ({reason}) for {ticker}"
    )

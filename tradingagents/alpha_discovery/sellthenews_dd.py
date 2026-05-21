from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

from tradingagents.integrations.sellthenews import SellTheNewsClient


@dataclass
class DDSourceSignal:
    source: str
    post_id: str
    raw_artifact_id: str
    reddit_title: str | None = None
    ai_title: str | None = None
    score: int | None = None
    comments: int | None = None
    posted_at: str | None = None
    ticker_sentiment: dict[str, str] = field(default_factory=dict)
    fact_check_status_counts: dict[str, int] = field(default_factory=dict)
    source_urls: list[str] = field(default_factory=list)
    holes: str | None = None
    discussion_summary: str | None = None


@dataclass
class DDCandidate:
    candidate_id: str
    ticker: str
    source: str
    tier: str
    alpha_score: float
    opportunity_type: str
    direction_hint: str
    catalyst_type: str
    evidence_summary: str
    thesis: str
    evidence: str
    source_signals: list[DDSourceSignal] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    rejected_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_signals"] = [asdict(signal) for signal in self.source_signals]
        return data


def collect_sellthenews_dd_candidates(
    client: SellTheNewsClient,
    *,
    limit: int = 20,
    max_posts: int = 3,
    min_score: int = 0,
    min_comments: int = 0,
    lang: str = "en",
) -> list[DDCandidate]:
    """Collect DD-driven Alpha Discovery candidates from SellTheNews WSB DD."""
    dd_list = client.call_tool("get_dd_list", {"lang": lang, "limit": limit, "offset": 0})
    summaries = _parse_dd_list(dd_list)
    candidates_by_ticker: dict[str, DDCandidate] = {}
    fetched_post_ids: set[str] = set()

    for summary in summaries:
        if len(fetched_post_ids) >= max_posts:
            break
        if summary.get("score") is not None and summary["score"] < min_score:
            continue
        if summary.get("comments") is not None and summary["comments"] < min_comments:
            continue

        post_id = str(summary["post_id"])
        fetched_post_ids.add(post_id)
        post_text = client.call_tool("get_dd_post", {"postId": post_id, "lang": lang})
        parsed = _parse_dd_post(post_text)
        signal = DDSourceSignal(
            source="sellthenews_wsb_dd",
            post_id=post_id,
            raw_artifact_id=f"mcp://sellthenews/dd/{post_id}",
            reddit_title=parsed.get("reddit_title") or summary.get("reddit_title"),
            ai_title=parsed.get("ai_title") or summary.get("ai_title"),
            score=parsed.get("score", summary.get("score")),
            comments=parsed.get("comments", summary.get("comments")),
            posted_at=summary.get("posted_at"),
            ticker_sentiment=parsed.get("ticker_sentiment") or summary.get("ticker_sentiment", {}),
            fact_check_status_counts=parsed.get("fact_check_status_counts", {}),
            source_urls=parsed.get("source_urls", []),
            holes=parsed.get("holes"),
            discussion_summary=parsed.get("discussion_summary"),
        )

        tickers = list(signal.ticker_sentiment) or list(summary.get("ticker_sentiment", {}))
        for ticker in tickers:
            score, tier, risk_flags, rejected_reason = _score_dd(signal, parsed)
            opportunity_type = _infer_opportunity_type(parsed, signal)
            direction_hint = _sentiment_to_direction(signal.ticker_sentiment.get(ticker))
            if ticker in candidates_by_ticker:
                candidate = candidates_by_ticker[ticker]
                candidate.source_signals.append(signal)
                candidate.alpha_score = round(max(candidate.alpha_score, score), 3)
                candidate.tier = _best_tier(candidate.tier, tier)
                candidate.risk_flags = sorted(set(candidate.risk_flags + risk_flags))
                if candidate.rejected_reason and not rejected_reason:
                    candidate.rejected_reason = None
            else:
                candidates_by_ticker[ticker] = DDCandidate(
                    candidate_id=f"{datetime.now(timezone.utc).date().isoformat()}-dd-{ticker.lower()}",
                    ticker=ticker,
                    source="sellthenews_wsb_dd",
                    tier=tier,
                    alpha_score=round(score, 3),
                    opportunity_type=opportunity_type,
                    direction_hint=direction_hint,
                    catalyst_type="social",
                    evidence_summary=parsed.get("summary") or signal.ai_title or signal.reddit_title or "",
                    thesis=parsed.get("thesis") or "",
                    evidence=parsed.get("evidence") or "",
                    source_signals=[signal],
                    risk_flags=risk_flags,
                    rejected_reason=rejected_reason,
                )

    return list(candidates_by_ticker.values())


def _parse_dd_list(text: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\n---\n", str(text or ""))
    posts: list[dict[str, Any]] = []
    for block in blocks:
        id_match = re.search(r"^\[([a-z0-9_-]{2,32})\]\s+(.+)$", block, flags=re.MULTILINE)
        if not id_match:
            continue
        reddit_title = _match_line(block, r"Reddit title:\s*(.+)")
        tickers = _parse_ticker_sentiment(_match_line(block, r"Tickers:\s*(.+)") or "")
        score_match = re.search(r"score=(-?\d+)\s*\|\s*comments=(\d+)\s*\|\s*(.+)$", block, flags=re.MULTILINE)
        posts.append(
            {
                "post_id": id_match.group(1),
                "ai_title": id_match.group(2).strip(),
                "reddit_title": reddit_title,
                "ticker_sentiment": tickers,
                "score": int(score_match.group(1)) if score_match else None,
                "comments": int(score_match.group(2)) if score_match else None,
                "posted_at": score_match.group(3).strip() if score_match else None,
            }
        )
    return posts


def _parse_dd_post(text: str) -> dict[str, Any]:
    body = str(text or "")
    return {
        "ai_title": _match_line(body, r"=== DD Post:\s*(.+?)\s*==="),
        "reddit_title": _match_line(body, r"Reddit title:\s*(.+)"),
        "score": _match_int(body, r"score:\s*(-?\d+)"),
        "comments": _match_int(body, r"comments:\s*(\d+)"),
        "ticker_sentiment": _parse_affected_tickers(body),
        "summary": _section(body, "--- Post Analysis Summary ---", "--- Discussion Summary ---"),
        "thesis": _section(body, "--- Post Analysis Summary ---", "--- Discussion Summary ---"),
        "evidence": _section(body, "--- Fact Check ---", "--- Original Post"),
        "holes": _extract_holes(body),
        "discussion_summary": _section(body, "--- Discussion Summary ---", "--- Fact Check ---"),
        "fact_check_status_counts": _fact_check_counts(body),
        "source_urls": _source_urls(body),
    }


def _parse_affected_tickers(text: str) -> dict[str, str]:
    section = _section(text, "Affected tickers:", "--- Post Analysis Summary ---")
    result: dict[str, str] = {}
    for ticker, sentiment in re.findall(r"-\s+([A-Z][A-Z0-9.\-]{0,7})\s+\(([^)]+)\)", section):
        result[ticker] = sentiment.strip().lower()
    return result


def _parse_ticker_sentiment(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for ticker, sentiment in re.findall(r"([A-Z][A-Z0-9.\-]{0,7})\(([^)]+)\)", text):
        result[ticker] = sentiment.strip().lower()
    return result


def _score_dd(signal: DDSourceSignal, parsed: dict[str, Any]) -> tuple[float, str, list[str], str | None]:
    counts = signal.fact_check_status_counts
    supported = counts.get("supported", 0)
    questionable = counts.get("questionable", 0)
    unsupported = counts.get("unsupported", 0)
    unclear = counts.get("unclear", 0)
    comments = signal.comments or 0
    score = signal.score or 0
    source_count = len(signal.source_urls)
    discussion = len(signal.discussion_summary or "")
    holes = len(signal.holes or "")

    quality = 0.25
    quality += min(supported, 5) * 0.08
    quality += min(source_count, 5) * 0.04
    quality += min(comments / 50, 0.2)
    quality += min(max(score, 0) / 300, 0.15)
    quality += 0.1 if discussion > 250 else 0
    quality -= min(questionable + unsupported, 5) * 0.12
    quality -= min(unclear, 5) * 0.03
    quality -= 0.08 if holes > 900 else 0
    quality = max(0.0, min(1.0, quality))

    risk_flags: list[str] = []
    if questionable or unsupported:
        risk_flags.append("fact_check_risk")
    if "short-dated" in (parsed.get("summary") or "").lower() or "options" in (parsed.get("summary") or "").lower():
        risk_flags.append("options_time_decay_risk")
    if comments < 5:
        risk_flags.append("thin_discussion")

    if unsupported + questionable >= max(2, supported):
        return quality, "Rejected", risk_flags, "fact-check risk dominates supported evidence"
    if quality >= 0.72:
        return quality, "A", risk_flags, None
    if quality >= 0.48:
        return quality, "B", risk_flags, None
    if quality >= 0.28:
        return quality, "C", risk_flags, None
    return quality, "Rejected", risk_flags, "DD quality score below threshold"


def _infer_opportunity_type(parsed: dict[str, Any], signal: DDSourceSignal) -> str:
    text = " ".join(
        str(parsed.get(key) or "") for key in ("summary", "discussion_summary", "evidence", "holes")
    ).lower()
    if signal.fact_check_status_counts.get("unsupported", 0) >= 2:
        return "avoid"
    if any(word in text for word in ("overvalued", "short thesis", "bear case", "puts")):
        return "reversal"
    if any(word in text for word in ("options", "implied volatility", "short-dated", "earnings")):
        return "volatility"
    if any(word in text for word in ("supplier", "competitor", "beneficiary", "indirect exposure", "stake")):
        return "second_order"
    return "continuation"


def _sentiment_to_direction(sentiment: str | None) -> str:
    value = str(sentiment or "").lower()
    if "bear" in value:
        return "bearish"
    if "bull" in value:
        return "bullish"
    if "mixed" in value:
        return "mixed"
    return "mixed"


def _best_tier(left: str, right: str) -> str:
    order = {"A": 0, "B": 1, "C": 2, "Rejected": 3}
    return left if order.get(left, 9) <= order.get(right, 9) else right


def _match_line(text: str, pattern: str) -> str | None:
    match = re.search(pattern, str(text or ""), flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _match_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _section(text: str, start: str, end: str | None = None) -> str:
    body = str(text or "")
    start_idx = body.find(start)
    if start_idx < 0:
        return ""
    start_idx += len(start)
    end_idx = body.find(end, start_idx) if end else -1
    if end_idx < 0:
        end_idx = len(body)
    return body[start_idx:end_idx].strip()


def _extract_holes(text: str) -> str:
    summary = _section(text, "--- Post Analysis Summary ---", "--- Discussion Summary ---")
    markers = ("weakness", "weaknesses", "risks", "holes", "dispute")
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    selected = [sentence for sentence in sentences if any(marker in sentence.lower() for marker in markers)]
    return " ".join(selected).strip()


def _fact_check_counts(text: str) -> dict[str, int]:
    counts = {"supported": 0, "questionable": 0, "unsupported": 0, "unclear": 0}
    for status in re.findall(r"\[(SUPPORTED|QUESTIONABLE|UNSUPPORTED|UNCLEAR)\]", str(text or "")):
        key = status.lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _source_urls(text: str) -> list[str]:
    urls = re.findall(r"Source:\s*.*?—\s*(https?://\S+)", str(text or ""))
    return [url.rstrip(").,") for url in urls]

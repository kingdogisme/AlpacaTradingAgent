from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from tradingagents.integrations.sellthenews import SellTheNewsClient

from .models import OpportunityCandidate, SourceSignal
from .sellthenews_dd import collect_sellthenews_dd_candidates
from .symbol_filters import is_ambiguous_symbol, is_common_stock_candidate, normalize_ticker


def collect_sellthenews_wsb_analysis(
    client: SellTheNewsClient,
    *,
    batch_id: str,
    top_sectors: int = 10,
    per_sector: int = 1,
    lang: str = "en",
) -> list[OpportunityCandidate]:
    text = client.call_tool("get_wsb_analysis", {"lang": lang, "offset": 0})
    sectors = _parse_sector_heatmap(text)[:top_sectors]
    sentiments = _parse_individual_sentiment(text)
    candidates: list[OpportunityCandidate] = []
    seen: set[str] = set()
    now = datetime.now(timezone.utc)
    ttl = (now + timedelta(days=1)).isoformat()

    for sector in sectors:
        sentiment_context = " ".join(
            value.get("raw_line", "") for ticker, value in sentiments.items() if ticker in sector["tickers"]
        )
        filter_context = f"{sector['theme']} {sector.get('raw_line', '')} {sentiment_context}"
        ranked = sorted(
            [ticker for ticker in sector["tickers"] if _eligible_wsb_ticker(ticker, sentiments, context=filter_context)],
            key=lambda ticker: sentiments.get(ticker, {}).get("mentions", 0),
            reverse=True,
        )
        for ticker in ranked[:per_sector]:
            if ticker in seen:
                continue
            seen.add(ticker)
            sentiment = sentiments.get(ticker, {})
            mentions = sentiment.get("mentions")
            heat_score = {"high": 0.65, "medium": 0.48, "low": 0.3}.get(sector["heat"], 0.25)
            mention_score = min(float(mentions or 0) / 100.0, 0.25)
            alpha_score = min(0.78, heat_score + mention_score)
            tier = "B" if alpha_score >= 0.58 else "C"
            direction = _sentiment_to_direction(str(sentiment.get("sentiment") or sector.get("sentiment") or "mixed"))
            signal = SourceSignal(
                candidate_id=_candidate_id(batch_id, ticker),
                source="sellthenews_wsb_analysis",
                raw_artifact_id=f"mcp://sellthenews/wsb_analysis/{batch_id}",
                source_timestamp=now.isoformat(),
                mentions=mentions,
                sentiment=sentiment.get("sentiment") or sector.get("sentiment"),
                evidence_json={
                    "theme": sector["theme"],
                    "heat": sector["heat"],
                    "representative_tickers": sector["tickers"],
                    "individual_sentiment": sentiment,
                },
            )
            candidates.append(
                OpportunityCandidate(
                    candidate_id=signal.candidate_id,
                    batch_id=batch_id,
                    ticker=ticker,
                    tier=tier,
                    alpha_score=round(alpha_score, 3),
                    opportunity_type="continuation",
                    direction_hint=direction,
                    theme=sector["theme"],
                    catalyst=f"WSB {sector['heat']} heat theme: {sector['theme']}",
                    ttl=ttl,
                    recommended_analysts=["market", "social", "news", "macro"],
                    run_reason=(
                        f"Top eligible ticker in WSB {sector['heat']} heat theme "
                        f"with {mentions or 0} mentions."
                    ),
                    discovered_at=now.isoformat(),
                    score_components={
                        "social_heat": heat_score,
                        "mention_score": mention_score,
                        "dd_quality": 0.0,
                        "news_confirmation": 0.0,
                        "price_volume_confirmation": 0.0,
                        "options_pressure": 0.0,
                        "crowding_penalty": 0.0,
                        "staleness_penalty": 0.0,
                        "continuation_score": round(alpha_score, 3),
                        "reversal_score": 0.0,
                        "volatility_score": 0.0,
                        "second_order_score": 0.0,
                        "confirmation_sources": [],
                        "promotion_gate": "social_only_max_b",
                    },
                    source_signals=[signal],
                    risk_flags=["social_attention"],
                )
            )
    return candidates


def collect_sellthenews_wsb_dd(
    client: SellTheNewsClient,
    *,
    batch_id: str,
    limit: int = 20,
    max_posts: int = 3,
    min_score: int = 0,
    min_comments: int = 0,
    lang: str = "en",
) -> list[OpportunityCandidate]:
    dd_candidates = collect_sellthenews_dd_candidates(
        client,
        limit=limit,
        max_posts=max_posts,
        min_score=min_score,
        min_comments=min_comments,
        lang=lang,
    )
    now = datetime.now(timezone.utc)
    ttl = (now + timedelta(days=7)).isoformat()
    converted: list[OpportunityCandidate] = []
    for dd in dd_candidates:
        filter_context = " ".join(
            part
            for part in (
                dd.evidence_summary,
                dd.thesis,
                dd.evidence,
                " ".join(signal.reddit_title or "" for signal in dd.source_signals),
                " ".join(signal.ai_title or "" for signal in dd.source_signals),
            )
            if part
        )
        if not is_common_stock_candidate(dd.ticker, context=filter_context):
            continue
        candidate_id = _candidate_id(batch_id, dd.ticker)
        signals: list[SourceSignal] = []
        for signal in dd.source_signals:
            signals.append(
                SourceSignal(
                    candidate_id=candidate_id,
                    source="sellthenews_wsb_dd",
                    raw_artifact_id=signal.raw_artifact_id,
                    source_timestamp=signal.posted_at,
                    mentions=signal.comments,
                    sentiment=signal.ticker_sentiment.get(dd.ticker),
                    evidence_json={
                        "post_id": signal.post_id,
                        "reddit_title": signal.reddit_title,
                        "ai_title": signal.ai_title,
                        "score": signal.score,
                        "comments": signal.comments,
                        "ticker_sentiment": signal.ticker_sentiment,
                        "fact_check_status_counts": signal.fact_check_status_counts,
                        "source_urls": signal.source_urls,
                        "holes": signal.holes,
                        "discussion_summary": signal.discussion_summary,
                        "thesis": dd.thesis,
                        "evidence": dd.evidence,
                    },
                )
            )
        converted.append(
            OpportunityCandidate(
                candidate_id=candidate_id,
                batch_id=batch_id,
                ticker=dd.ticker,
                tier=dd.tier,
                alpha_score=dd.alpha_score,
                opportunity_type=dd.opportunity_type,
                direction_hint=dd.direction_hint,
                theme="WSB DD",
                catalyst=dd.evidence_summary[:500],
                ttl=ttl,
                recommended_analysts=["market", "social", "news", "fundamentals"],
                run_reason="WSB DD thesis with quality-scored fact-check and discussion evidence.",
                rejected_reason=dd.rejected_reason,
                discovered_at=now.isoformat(),
                score_components={
                    "social_heat": 0.0,
                    "dd_quality": dd.alpha_score,
                    "news_confirmation": 0.0,
                    "price_volume_confirmation": 0.0,
                    "options_pressure": 0.0,
                    "crowding_penalty": 0.0,
                    "staleness_penalty": 0.0,
                    "continuation_score": dd.alpha_score if dd.opportunity_type == "continuation" else 0.0,
                    "reversal_score": dd.alpha_score if dd.opportunity_type == "reversal" else 0.0,
                    "volatility_score": dd.alpha_score if dd.opportunity_type == "volatility" else 0.0,
                    "second_order_score": dd.alpha_score if dd.opportunity_type == "second_order" else 0.0,
                    "confirmation_sources": [],
                    "promotion_gate": "dd_full_post_required",
                },
                source_signals=signals,
                risk_flags=dd.risk_flags,
            )
        )
    return converted


def merge_candidates(candidates: list[OpportunityCandidate]) -> list[OpportunityCandidate]:
    by_ticker: dict[str, OpportunityCandidate] = {}
    for candidate in candidates:
        ticker = candidate.ticker.upper()
        if ticker not in by_ticker:
            by_ticker[ticker] = candidate
            continue
        existing = by_ticker[ticker]
        existing.source_signals.extend(candidate.source_signals)
        existing.alpha_score = round(max(existing.alpha_score, candidate.alpha_score), 3)
        existing.tier = _best_tier(existing.tier, candidate.tier)
        existing.risk_flags = sorted(set(existing.risk_flags + candidate.risk_flags))
        existing.score_components = _merge_score_components(
            existing.score_components,
            candidate.score_components,
        )
        if existing.rejected_reason and not candidate.rejected_reason:
            existing.rejected_reason = None
        if not existing.catalyst and candidate.catalyst:
            existing.catalyst = candidate.catalyst
        if candidate.theme and candidate.theme not in str(existing.theme or ""):
            existing.theme = ", ".join(part for part in (existing.theme, candidate.theme) if part)
    return list(by_ticker.values())


def _eligible_wsb_ticker(ticker: str, sentiments: dict[str, dict[str, Any]], *, context: str = "") -> bool:
    ticker = normalize_ticker(ticker)
    sentiment = sentiments.get(ticker, {})
    sentiment_context = f"{context} {sentiment.get('raw_line', '')}"
    if not is_common_stock_candidate(ticker, context=sentiment_context):
        return False
    if ticker not in sentiments:
        return False
    mentions = sentiments.get(ticker, {}).get("mentions")
    return mentions is not None and int(mentions) > 0


def _parse_sector_heatmap(text: str) -> list[dict[str, Any]]:
    section = _section(text, "Sector Heatmap", "Individual Stock Sentiment")
    sectors: list[dict[str, Any]] = []
    for raw_line in section.splitlines():
        line = raw_line.strip(" -|\t")
        if not line or "Ticker" in line and "Sentiment" in line:
            continue
        if "|" in raw_line:
            parts = [part.strip() for part in raw_line.split("|") if part.strip()]
            ticker_source = parts[-1] if parts else line
        else:
            ticker_source = line
        tickers = [normalize_ticker(ticker) for ticker in re.findall(r"\b[A-Z][A-Z0-9.\-]{0,5}\b", ticker_source)]
        tickers = [ticker for ticker in tickers if ticker not in {"HIGH", "MEDIUM", "LOW"}]
        if not tickers:
            continue
        heat = "medium"
        if re.search(r"\bhigh\b", line, flags=re.IGNORECASE):
            heat = "high"
        elif re.search(r"\blow\b", line, flags=re.IGNORECASE):
            heat = "low"
        sentiment = "mixed"
        for label in ("strongly bullish", "strong bullish", "bullish", "strongly bearish", "strong bearish", "bearish", "neutral", "mixed"):
            if label in line.lower():
                sentiment = label.replace("strongly ", "strong_").replace("strong ", "strong_").replace(" ", "_")
                break
        theme = line
        if "|" in raw_line:
            parts = [part.strip() for part in raw_line.split("|") if part.strip()]
            if parts:
                theme = parts[0]
        sectors.append({"theme": theme[:120], "heat": heat, "sentiment": sentiment, "tickers": tickers, "raw_line": line})
    return sectors


def _parse_individual_sentiment(text: str) -> dict[str, dict[str, Any]]:
    section = _section(text, "Individual Stock Sentiment", "")
    result: dict[str, dict[str, Any]] = defaultdict(dict)
    for line in section.splitlines():
        ticker_match = re.search(r"\b([A-Z][A-Z0-9.\-]{0,5})\b", line)
        if not ticker_match:
            continue
        ticker = normalize_ticker(ticker_match.group(1))
        if is_ambiguous_symbol(ticker) and not is_common_stock_candidate(ticker, context=line):
            continue
        mentions_match = re.search(r"(\d+)\+?", line)
        sentiment = "mixed"
        for label in ("strongly bullish", "strong bullish", "bullish", "strongly bearish", "strong bearish", "bearish", "neutral", "mixed"):
            if label in line.lower():
                sentiment = label.replace("strongly ", "strong_").replace("strong ", "strong_").replace(" ", "_")
                break
        result[ticker] = {
            "mentions": int(mentions_match.group(1)) if mentions_match else None,
            "sentiment": sentiment,
            "raw_line": line,
        }
    return dict(result)


def _section(text: str, start: str, end: str) -> str:
    body = str(text or "")
    start_match = re.search(re.escape(start), body, flags=re.IGNORECASE)
    if not start_match:
        return body
    start_idx = start_match.end()
    if not end:
        return body[start_idx:]
    end_match = re.search(re.escape(end), body[start_idx:], flags=re.IGNORECASE)
    end_idx = start_idx + end_match.start() if end_match else len(body)
    return body[start_idx:end_idx]


def _sentiment_to_direction(sentiment: str) -> str:
    lowered = sentiment.lower()
    if "bear" in lowered:
        return "bearish"
    if "bull" in lowered:
        return "bullish"
    return "mixed"


def _best_tier(left: str, right: str) -> str:
    order = {"A": 0, "B": 1, "C": 2, "Rejected": 3}
    return left if order.get(left, 9) <= order.get(right, 9) else right


def _candidate_id(batch_id: str, ticker: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", ticker.lower()).strip("-")
    return f"{batch_id}-{safe}"


def _merge_score_components(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key == "confirmation_sources":
            merged[key] = sorted(set((merged.get(key) or []) + (value or [])))
        elif isinstance(value, (int, float)):
            merged[key] = max(float(merged.get(key, 0.0) or 0.0), float(value))
        elif key not in merged or not merged[key]:
            merged[key] = value
    return merged

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Protocol

from tradingagents.integrations.sellthenews import (
    SellTheNewsBadResponse,
    SellTheNewsClient,
    SellTheNewsUnavailable,
    looks_sparse,
)
from tradingagents.dataflows.freshness import date_age_days, freshest_date_in_text, is_fresh_date

from .models import OpportunityCandidate, SourceSignal


class MarketDataProvider(Protocol):
    def price_volume_confirmation(self, ticker: str) -> dict:
        ...


class FundamentalDataProvider(Protocol):
    def sec_fundamental_confirmation(self, ticker: str) -> dict:
        ...


@dataclass
class ConfirmationConfig:
    news_enabled: bool = True
    search_news_enabled: bool = False
    live_news_enabled: bool = False
    policy_social_enabled: bool = False
    options_enabled: bool = True
    price_volume_enabled: bool = False
    sec_fundamental_enabled: bool = False
    min_confirmations_for_a: int = 1
    min_confirmations_for_dd_a: int = 2
    news_max_age_days: int = 14
    require_news_date: bool = True


@dataclass
class ConfirmationHit:
    source: str
    strength: float


def apply_confirmations(
    candidates: list[OpportunityCandidate],
    *,
    client: SellTheNewsClient,
    market_data_provider: MarketDataProvider | None = None,
    fundamental_data_provider: FundamentalDataProvider | None = None,
    config: ConfirmationConfig | None = None,
) -> list[OpportunityCandidate]:
    cfg = config or ConfirmationConfig()
    for candidate in candidates:
        if candidate.tier == "Rejected":
            continue
        hits: list[ConfirmationHit] = []
        news_hit = _add_stock_news_confirmation(candidate, client, cfg) if cfg.news_enabled else None
        if news_hit:
            hits.append(news_hit)
        search_hit = _add_search_news_confirmation(candidate, client, cfg) if cfg.search_news_enabled else None
        if search_hit:
            hits.append(search_hit)
        live_hit = _add_live_news_confirmation(candidate, client, cfg) if cfg.live_news_enabled else None
        if live_hit:
            hits.append(live_hit)
        policy_hit = _add_policy_social_confirmation(candidate, client, cfg) if cfg.policy_social_enabled else None
        if policy_hit:
            hits.append(policy_hit)
        if cfg.options_enabled and _add_options_confirmation(candidate, client):
            hits.append(ConfirmationHit("options", 0.12))
        if cfg.price_volume_enabled and market_data_provider:
            price_volume_hit = _add_price_volume_confirmation(candidate, market_data_provider)
            if price_volume_hit:
                hits.append(price_volume_hit)
        if cfg.sec_fundamental_enabled and fundamental_data_provider:
            sec_hit = _add_sec_fundamental_confirmation(candidate, fundamental_data_provider)
            if sec_hit:
                hits.append(sec_hit)

        components = dict(candidate.score_components or {})
        prior_confirmations = components.get("confirmation_sources") or []
        confirmations = [hit.source for hit in hits]
        components["confirmation_sources"] = sorted(set(prior_confirmations + confirmations))
        news_strength = min(
            0.24,
            sum(
                hit.strength
                for hit in hits
                if hit.source in {"direct_news", "search_news", "live_news", "policy_social"}
            ),
        )
        options_strength = max((hit.strength for hit in hits if hit.source == "options"), default=0.0)
        price_volume_strength = max((hit.strength for hit in hits if hit.source == "price_volume"), default=0.0)
        sec_strength = max((hit.strength for hit in hits if hit.source == "sec_filing"), default=0.0)
        components["news_confirmation"] = max(float(components.get("news_confirmation", 0.0) or 0.0), news_strength)
        components["options_pressure"] = max(float(components.get("options_pressure", 0.0) or 0.0), options_strength)
        components["price_volume_confirmation"] = max(
            float(components.get("price_volume_confirmation", 0.0) or 0.0),
            price_volume_strength,
        )
        components["fundamental_confirmation"] = max(
            float(components.get("fundamental_confirmation", 0.0) or 0.0),
            sec_strength,
        )
        candidate.score_components = components
        _apply_promotion_gate(
            candidate,
            min_confirmations_for_a=cfg.min_confirmations_for_a,
            min_confirmations_for_dd_a=cfg.min_confirmations_for_dd_a,
        )
    return candidates


def _add_stock_news_confirmation(
    candidate: OpportunityCandidate,
    client: SellTheNewsClient,
    cfg: ConfirmationConfig,
) -> ConfirmationHit | None:
    try:
        text = client.call_tool("get_stock_news", {"ticker": candidate.ticker, "limit": 5, "offset": 0})
    except (SellTheNewsUnavailable, SellTheNewsBadResponse, KeyError):
        return None
    return _add_text_confirmation(
        candidate,
        text,
        source_name="sellthenews_stock_news_confirmation",
        confirmation_source="direct_news",
        raw_artifact_id=f"mcp://sellthenews/stock_news/{candidate.ticker}",
        strength_multiplier=1.0,
        config=cfg,
    )


def _add_search_news_confirmation(
    candidate: OpportunityCandidate,
    client: SellTheNewsClient,
    cfg: ConfirmationConfig,
) -> ConfirmationHit | None:
    query = " ".join(
        part
        for part in (
            candidate.ticker,
            candidate.theme,
            candidate.catalyst,
            "stock catalyst",
        )
        if part
    )[:220]
    try:
        text = client.call_tool(
            "search_news",
            {"query": query, "limit": 5, "offset": 0, "sort": "time", "lang": "en"},
        )
    except (SellTheNewsUnavailable, SellTheNewsBadResponse, KeyError):
        return None
    return _add_text_confirmation(
        candidate,
        text,
        source_name="sellthenews_search_news_confirmation",
        confirmation_source="search_news",
        raw_artifact_id=f"mcp://sellthenews/search_news/{candidate.ticker}",
        strength_multiplier=0.85,
        config=cfg,
    )


def _add_live_news_confirmation(
    candidate: OpportunityCandidate,
    client: SellTheNewsClient,
    cfg: ConfirmationConfig,
) -> ConfirmationHit | None:
    try:
        text = client.call_tool(
            "get_live_news",
            {"limit": 10, "offset": 0, "marketOnly": False, "lang": "en"},
        )
    except (SellTheNewsUnavailable, SellTheNewsBadResponse, KeyError):
        return None
    return _add_text_confirmation(
        candidate,
        text,
        source_name="sellthenews_live_news_confirmation",
        confirmation_source="live_news",
        raw_artifact_id=f"mcp://sellthenews/live_news/{candidate.ticker}",
        strength_multiplier=0.75,
        config=cfg,
    )


def _add_policy_social_confirmation(
    candidate: OpportunityCandidate,
    client: SellTheNewsClient,
    cfg: ConfirmationConfig,
) -> ConfirmationHit | None:
    query = " ".join(part for part in (candidate.ticker, candidate.theme, candidate.catalyst) if part)[:220]
    try:
        text = client.call_tool(
            "get_trump_posts",
            {"query": query, "limit": 10, "offset": 0, "lang": "en"},
        )
    except (SellTheNewsUnavailable, SellTheNewsBadResponse, KeyError):
        return None
    return _add_text_confirmation(
        candidate,
        text,
        source_name="sellthenews_policy_social_confirmation",
        confirmation_source="policy_social",
        raw_artifact_id=f"mcp://sellthenews/trump_posts/{candidate.ticker}",
        strength_multiplier=0.65,
        config=cfg,
    )


def _add_text_confirmation(
    candidate: OpportunityCandidate,
    text: str,
    *,
    source_name: str,
    confirmation_source: str,
    raw_artifact_id: str,
    strength_multiplier: float,
    config: ConfirmationConfig,
) -> ConfirmationHit | None:
    match = _score_news_match(candidate, text)
    if not match:
        return None
    freshest_source_date = freshest_date_in_text(text)
    as_of = _confirmation_as_of(candidate, freshest_source_date=freshest_source_date)
    if config.require_news_date and freshest_source_date is None:
        return None
    if freshest_source_date is not None and not is_fresh_date(
        freshest_source_date,
        as_of=as_of,
        max_age_days=config.news_max_age_days,
    ):
        return None
    strength = round(float(match["strength"]) * strength_multiplier, 3)
    candidate.source_signals.append(
        SourceSignal(
            candidate_id=candidate.candidate_id,
            source=source_name,
            raw_artifact_id=raw_artifact_id,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            evidence_json={
                "confirmation_type": confirmation_source,
                "summary": text[:1200],
                "matched_keywords": match["matched_keywords"],
                "event_keywords": match["event_keywords"],
                "confirmation_strength": strength,
                "freshest_source_date": freshest_source_date.isoformat() if freshest_source_date else None,
                "source_age_days": date_age_days(freshest_source_date, as_of=as_of),
                "max_age_days": config.news_max_age_days,
            },
        )
    )
    return ConfirmationHit(confirmation_source, strength)


def _confirmation_as_of(candidate: OpportunityCandidate, *, freshest_source_date=None) -> str:
    for raw in (getattr(candidate, "discovered_at", None), getattr(candidate, "created_at", None)):
        if not raw:
            continue
        text = str(raw).strip()
        try:
            candidate_date = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
            if match:
                candidate_date = datetime.fromisoformat(match.group(0)).date()
            else:
                continue
        if freshest_source_date is None or date_age_days(freshest_source_date, as_of=candidate_date) >= -1:
            return candidate_date.isoformat()
        break
    return datetime.now(timezone.utc).date().isoformat()


def _add_options_confirmation(candidate: OpportunityCandidate, client: SellTheNewsClient) -> bool:
    try:
        text = client.call_tool("get_options_data", {"ticker": candidate.ticker, "greeks": "gamma"})
    except (SellTheNewsUnavailable, SellTheNewsBadResponse, KeyError):
        return False
    lowered = text.lower()
    has_exposure = any(marker in lowered for marker in ("gamma flip", "net gex", "call wall", "put wall", "exposure"))
    if looks_sparse(text, min_chars=220) or not has_exposure:
        return False
    candidate.source_signals.append(
        SourceSignal(
            candidate_id=candidate.candidate_id,
            source="sellthenews_options_confirmation",
            raw_artifact_id=f"mcp://sellthenews/options/{candidate.ticker}",
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            evidence_json={"confirmation_type": "options", "summary": text[:1200]},
        )
    )
    return True


def _add_price_volume_confirmation(
    candidate: OpportunityCandidate,
    provider: MarketDataProvider,
) -> ConfirmationHit | None:
    data = provider.price_volume_confirmation(candidate.ticker)
    confirmed = bool(data.get("confirmed"))
    if confirmed:
        if data.get("overextended"):
            if "price_move_overextended" not in candidate.risk_flags:
                candidate.risk_flags.append("price_move_overextended")
        candidate.source_signals.append(
            SourceSignal(
                candidate_id=candidate.candidate_id,
                source="alpaca_price_volume_confirmation",
                raw_artifact_id=f"alpaca://price_volume/{candidate.ticker}",
                source_timestamp=datetime.now(timezone.utc).isoformat(),
                evidence_json=data,
            )
        )
        return ConfirmationHit("price_volume", float(data.get("confirmation_strength", 0.18) or 0.18))
    return None


def _add_sec_fundamental_confirmation(
    candidate: OpportunityCandidate,
    provider: FundamentalDataProvider,
) -> ConfirmationHit | None:
    try:
        data = provider.sec_fundamental_confirmation(candidate.ticker)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    flags = data.get("flags") or []
    risk_flags = data.get("risk_flags") or []
    for flag in risk_flags:
        if flag not in candidate.risk_flags:
            candidate.risk_flags.append(str(flag))
    candidate.source_signals.append(
        SourceSignal(
            candidate_id=candidate.candidate_id,
            source="sec_edgar_fundamental_confirmation",
            raw_artifact_id=f"sec://edgar/companyfacts/{candidate.ticker}",
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            evidence_json={
                "confirmation_type": "sec_filing",
                "confirmed": bool(data.get("confirmed")),
                "flags": flags,
                "summary": str(data.get("summary") or "")[:1200],
                "cik": data.get("cik"),
            },
        )
    )
    if not data.get("confirmed"):
        return None
    return ConfirmationHit("sec_filing", float(data.get("strength", 0.03) or 0.03))


def _apply_promotion_gate(
    candidate: OpportunityCandidate,
    *,
    min_confirmations_for_a: int,
    min_confirmations_for_dd_a: int,
) -> None:
    components = candidate.score_components or {}
    confirmations = components.get("confirmation_sources") or []
    gate_confirmations = [source for source in confirmations if source != "sec_filing"]
    confirmation_count = len(gate_confirmations)
    required_confirmations = min_confirmations_for_a
    if _is_dd_candidate(candidate):
        required_confirmations = max(required_confirmations, min_confirmations_for_dd_a)
    base = float(candidate.alpha_score or 0.0)
    confirmation_bonus = (
        float(components.get("news_confirmation", 0.0) or 0.0)
        + float(components.get("price_volume_confirmation", 0.0) or 0.0)
        + float(components.get("options_pressure", 0.0) or 0.0)
        + float(components.get("fundamental_confirmation", 0.0) or 0.0)
    )
    candidate.alpha_score = round(min(1.0, base + confirmation_bonus), 3)
    if _has_direction_conflict(candidate):
        if candidate.tier == "A":
            candidate.tier = "B"
        components["promotion_gate"] = "blocked_direction_conflict"
        if "direction_conflict" not in candidate.risk_flags:
            candidate.risk_flags.append("direction_conflict")
    elif _has_weak_social_evidence(candidate):
        if candidate.tier == "A":
            candidate.tier = "B"
        components["promotion_gate"] = "blocked_weak_social_evidence"
        if "weak_social_evidence" not in candidate.risk_flags:
            candidate.risk_flags.append("weak_social_evidence")
    elif "price_move_overextended" in candidate.risk_flags:
        if candidate.tier == "A":
            candidate.tier = "B"
        components["promotion_gate"] = "blocked_overextended_price"
    elif _has_dd_fact_check_risk(candidate):
        if candidate.tier == "A":
            candidate.tier = "B"
        components["promotion_gate"] = "blocked_dd_fact_check_risk"
    elif confirmation_count >= required_confirmations and candidate.alpha_score >= 0.82:
        candidate.tier = "A"
        components["promotion_gate"] = "passed_independent_confirmation"
    elif candidate.tier == "A":
        candidate.tier = "B"
        components["promotion_gate"] = "blocked_missing_independent_confirmation"
    elif _is_dd_candidate(candidate) and confirmation_count < required_confirmations:
        components["promotion_gate"] = "blocked_missing_dd_confirmations"
    else:
        components["promotion_gate"] = components.get("promotion_gate") or "not_a_candidate"
    opportunity_scores = [
        float(components.get("continuation_score", 0.0) or 0.0),
        float(components.get("reversal_score", 0.0) or 0.0),
        float(components.get("volatility_score", 0.0) or 0.0),
        float(components.get("second_order_score", 0.0) or 0.0),
    ]
    components["best_opportunity_score"] = round(max(opportunity_scores + [base]) + confirmation_bonus, 3)
    candidate.score_components = components


def _score_news_match(candidate: OpportunityCandidate, text: str) -> dict | None:
    if looks_sparse(text, min_chars=220):
        return None
    if not re.search(rf"\b{re.escape(candidate.ticker)}\b", str(text or ""), flags=re.IGNORECASE):
        return None

    context_keywords = _candidate_context_keywords(candidate)
    text_keywords = _keyword_set(text)
    matched = sorted(context_keywords & text_keywords)
    event_keywords = sorted(_EVENT_KEYWORDS & text_keywords)

    if not matched:
        return None
    if len(matched) < 2 and not event_keywords:
        return None

    strength = 0.10 + min(len(matched) * 0.025, 0.06)
    if event_keywords:
        strength += 0.03
    return {
        "matched_keywords": matched[:12],
        "event_keywords": event_keywords[:12],
        "strength": round(min(0.16, strength), 3),
    }


def _candidate_context_keywords(candidate: OpportunityCandidate) -> set[str]:
    parts = [
        candidate.theme or "",
        candidate.catalyst or "",
        candidate.run_reason or "",
        candidate.opportunity_type or "",
    ]
    for signal in candidate.source_signals:
        evidence = signal.evidence_json or {}
        for key in ("theme", "thesis", "evidence", "reddit_title", "ai_title", "discussion_summary"):
            value = evidence.get(key)
            if isinstance(value, str):
                parts.append(value[:800])
    return _keyword_set(" ".join(parts)) - {candidate.ticker.lower()}


def _keyword_set(text: str) -> set[str]:
    result: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9&+.-]{2,}", str(text or "")):
        normalized = _normalize_token(token)
        if normalized and normalized not in _STOPWORDS:
            result.add(normalized)
    return result


def _normalize_token(token: str) -> str:
    normalized = token.lower().strip(".-+&")
    if len(normalized) > 4 and normalized.endswith("s"):
        normalized = normalized[:-1]
    return normalized


def _has_direction_conflict(candidate: OpportunityCandidate) -> bool:
    direction = str(candidate.direction_hint or "").lower()
    opportunity_type = str(candidate.opportunity_type or "").lower()
    return opportunity_type == "continuation" and direction == "bearish"


def _is_dd_candidate(candidate: OpportunityCandidate) -> bool:
    if str(candidate.theme or "").lower() == "wsb dd":
        return True
    return any(signal.source == "sellthenews_wsb_dd" for signal in candidate.source_signals)


def _has_dd_fact_check_risk(candidate: OpportunityCandidate) -> bool:
    if not _is_dd_candidate(candidate):
        return False
    if "fact_check_risk" in (candidate.risk_flags or []):
        return True
    return any(
        signal.evidence_json.get("fact_check_status_counts", {}).get("unsupported", 0)
        or signal.evidence_json.get("fact_check_status_counts", {}).get("questionable", 0)
        for signal in candidate.source_signals
    )


def _has_weak_social_evidence(candidate: OpportunityCandidate) -> bool:
    if _is_dd_candidate(candidate):
        return False
    mentions = [
        int(signal.mentions or 0)
        for signal in candidate.source_signals
        if signal.source == "sellthenews_wsb_analysis"
    ]
    if not mentions:
        return False
    max_mentions = max(mentions)
    direction = str(candidate.direction_hint or "").lower()
    if max_mentions < 10:
        return True
    return direction in {"mixed", "neutral"} and max_mentions < 20


_STOPWORDS = {
    "about",
    "after",
    "analysis",
    "analyst",
    "article",
    "bearish",
    "because",
    "bullish",
    "candidate",
    "catalyst",
    "company",
    "confirm",
    "confirms",
    "daily",
    "direct",
    "discussion",
    "evidence",
    "expected",
    "from",
    "high",
    "heat",
    "market",
    "medium",
    "mixed",
    "news",
    "price",
    "report",
    "reports",
    "sector",
    "sentiment",
    "share",
    "stock",
    "summary",
    "theme",
    "ticker",
    "total",
    "trading",
    "update",
    "with",
    "wsb",
}

_EVENT_KEYWORDS = {
    "acquisition",
    "approval",
    "buyback",
    "contract",
    "earnings",
    "fda",
    "filing",
    "forecast",
    "guidance",
    "lawsuit",
    "merger",
    "offering",
    "order",
    "partnership",
    "pricing",
    "profit",
    "revenue",
    "sec",
    "settlement",
    "shipment",
}

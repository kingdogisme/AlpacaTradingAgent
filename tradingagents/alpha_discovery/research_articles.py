from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .symbol_filters import normalize_ticker


ARTICLE_KINDS = {
    "single_ticker_dd",
    "thematic_dd",
    "news_digest",
    "portfolio_update",
    "macro_note",
    "other",
}

RESEARCH_TICKER_STOPWORDS = {
    "AC",
    "AIDC",
    "AI",
    "ASIC",
    "CEO",
    "CPU",
    "CXL",
    "DC",
    "DD",
    "DEEP",
    "DRAM",
    "ETF",
    "FET",
    "GAN",
    "GB",
    "GPU",
    "HBM",
    "HVDC",
    "IPO",
    "MLCC",
    "MOSFET",
    "NAND",
    "OEM",
    "PCB",
    "PDU",
    "SIC",
    "SST",
    "UPS",
    "VCSEL",
}


@dataclass
class ResearchArticleEvidence:
    article_kind: str = "other"
    primary_tickers: list[str] = field(default_factory=list)
    secondary_tickers: list[str] = field(default_factory=list)
    depth_score: float = 0.0
    novelty_score: float = 0.0
    conviction_score: float = 0.0
    source_quality: float = 0.5
    direction_hint: str = "unknown"
    thesis: str | None = None
    risks: list[str] = field(default_factory=list)
    watch_items: list[str] = field(default_factory=list)
    time_horizon: str | None = None

    @property
    def evidence_quality(self) -> float:
        return round(self.depth_score * self.novelty_score * self.conviction_score * self.source_quality, 3)

    def asdict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_quality"] = self.evidence_quality
        return data


@dataclass
class CandidateImpact:
    ticker: str
    role: str
    research_boost: float
    max_tier: str
    confirmation: bool
    promotion_gate: str
    reason: str

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


def classify_research_article(
    event: dict[str, Any],
    *,
    source_quality_map: dict[str, float] | None = None,
) -> ResearchArticleEvidence:
    source = event.get("source") or {}
    article = event.get("article") or {}
    analysis = event.get("analysis") or {}
    title = str(article.get("title") or "")
    summary = str(analysis.get("summary_zh") or "")
    excerpt = str(article.get("excerpt") or "")
    text = " ".join([title, summary, excerpt])
    source_id = str(source.get("id") or source.get("name") or "unknown").lower()
    source_quality = _source_quality(source_id, source_quality_map or {})

    explicit_primary = _extract_tickers(analysis.get("companies_or_tickers"))
    kind = _article_kind(title, summary, excerpt, explicit_primary)
    primary = _primary_tickers(analysis.get("companies_or_tickers"), title, kind)
    secondary = _extract_secondary_tickers(text, primary)
    if kind == "news_digest" and not _normalize_list(analysis.get("companies_or_tickers")):
        primary = []
    depth = _depth_score(text, kind)
    novelty = _novelty_score(text, summary)
    conviction = _conviction_score(text)

    return ResearchArticleEvidence(
        article_kind=kind,
        primary_tickers=primary,
        secondary_tickers=secondary,
        depth_score=depth,
        novelty_score=novelty,
        conviction_score=conviction,
        source_quality=source_quality,
        direction_hint=_direction_hint(text),
        thesis=summary[:600] or title,
        risks=_extract_list_items(summary, ["风险", "risk"]),
        watch_items=_normalize_list(analysis.get("watch_items")),
        time_horizon=_time_horizon(text),
    )


def build_candidate_impacts(
    evidence: ResearchArticleEvidence,
    *,
    boost_max: float = 0.24,
    single_article_a_gate: bool = True,
) -> list[CandidateImpact]:
    impacts: list[CandidateImpact] = []
    if evidence.article_kind == "news_digest":
        return impacts
    primary_cap = 0.32 if evidence.article_kind == "single_ticker_dd" and evidence.source_quality >= 0.8 else boost_max
    primary_boost = min(primary_cap, evidence.evidence_quality)
    for ticker in evidence.primary_tickers:
        confirmation = evidence.article_kind == "single_ticker_dd" and primary_boost >= 0.22
        max_tier = "A" if single_article_a_gate and confirmation else "B"
        gate = "passed_research_dd_gate" if max_tier == "A" else "research_article_confirmation"
        impacts.append(
            CandidateImpact(
                ticker=ticker,
                role="primary",
                research_boost=round(primary_boost, 3),
                max_tier=max_tier,
                confirmation=confirmation,
                promotion_gate=gate,
                reason=f"{evidence.article_kind} primary ticker with research quality {evidence.evidence_quality:.3f}",
            )
        )

    secondary_boost = min(0.12, evidence.evidence_quality * 0.5)
    for ticker in evidence.secondary_tickers:
        impacts.append(
            CandidateImpact(
                ticker=ticker,
                role="secondary",
                research_boost=round(secondary_boost, 3),
                max_tier="B",
                confirmation=False,
                promotion_gate="research_article_second_order",
                reason=f"{evidence.article_kind} secondary ticker/theme exposure",
            )
        )
    return impacts


def enriched_payload(evidence: ResearchArticleEvidence, impacts: list[CandidateImpact]) -> dict[str, Any]:
    return {
        "article_kind": evidence.article_kind,
        "primary_tickers": evidence.primary_tickers,
        "secondary_tickers": evidence.secondary_tickers,
        "evidence_quality": evidence.evidence_quality,
        "candidate_impacts": [impact.asdict() for impact in impacts],
    }


def _source_quality(source_id: str, source_quality_map: dict[str, float]) -> float:
    for key, value in source_quality_map.items():
        if key.lower() in source_id:
            return _clamp(float(value), 0.0, 1.0)
    defaults = {
        "irrationalanalysis": 0.86,
        "semianalysis": 0.9,
        "citrini": 0.82,
        "theshuffledeep": 0.78,
        "theshufflelight": 0.65,
    }
    for key, value in defaults.items():
        if key in source_id:
            return value
    return 0.55


def _article_kind(title: str, summary: str, excerpt: str, primary: list[str]) -> str:
    text = " ".join([title, summary, excerpt]).lower()
    if any(marker in text for marker in ["portfolio", "holdings", "持仓", "组合"]):
        return "portfolio_update"
    if re.search(r"\b(macro|fed|tariff|war)\b", text) or any(marker in text for marker in ["美元", "宏观"]):
        return "macro_note"
    if any(marker in text for marker in ["roundup", "digest", "最近", "周报"]):
        return "news_digest"
    dd_markers = ["deep dive", "equity research", "深度", "analysis", "dd", "研究", "thesis"]
    if primary and any(marker in text for marker in dd_markers):
        return "single_ticker_dd"
    if any(marker in text for marker in ["theme", "basket", "value chain", "supply chain", "主题", "价值链"]):
        return "thematic_dd"
    return "single_ticker_dd" if primary and len(text) > 900 else "other"


def _depth_score(text: str, kind: str) -> float:
    lowered = text.lower()
    markers = ["valuation", "估值", "risk", "风险", "margin", "毛利", "revenue", "收入", "thesis", "variant", "data", "数据"]
    score = 0.35 + min(0.45, sum(0.07 for marker in markers if marker in lowered))
    if kind in {"single_ticker_dd", "thematic_dd"}:
        score += 0.12
    if len(text) > 1200:
        score += 0.08
    return round(_clamp(score, 0.0, 1.0), 3)


def _novelty_score(text: str, summary: str) -> float:
    lowered = " ".join([text, summary]).lower()
    score = 0.45
    if any(marker in lowered for marker in ["new", "inflect", "mispriced", "新", "重估", "错定价", "价值迁移"]):
        score += 0.25
    if any(marker in lowered for marker in ["consensus", "well known", "复述", "共识"]):
        score -= 0.15
    if len(text) > 1200:
        score += 0.1
    return round(_clamp(score, 0.0, 1.0), 3)


def _conviction_score(text: str) -> float:
    lowered = text.lower()
    score = 0.45
    if any(marker in lowered for marker in ["strong", "must", "核心", "必须", "值得", "high conviction"]):
        score += 0.18
    if any(marker in lowered for marker in ["maybe", "unclear", "unknown", "不确定", "观察"]):
        score -= 0.08
    if any(marker in lowered for marker in ["because", "therefore", "原因", "因为", "所以"]):
        score += 0.08
    return round(_clamp(score, 0.0, 1.0), 3)


def _direction_hint(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ["avoid", "short", "bearish", "看空", "规避"]):
        return "bearish"
    if any(marker in lowered for marker in ["bullish", "long", "upside", "看多", "机会"]):
        return "bullish"
    if any(marker in lowered for marker in ["mixed", "unclear", "双刃剑"]):
        return "mixed"
    return "unknown"


def _time_horizon(text: str) -> str | None:
    lowered = text.lower()
    if any(marker in lowered for marker in ["2026", "2027", "multi-year", "长期", "多年"]):
        return "multi_quarter"
    if any(marker in lowered for marker in ["q1", "q2", "q3", "q4", "季度"]):
        return "quarterly"
    return None


def _primary_tickers(values: Any, title: str, kind: str) -> list[str]:
    explicit = _extract_tickers(values)
    if explicit:
        return explicit
    if kind == "news_digest":
        return []
    return _extract_tickers(title)


def _extract_tickers(values: Any) -> list[str]:
    tickers = []
    stopwords = RESEARCH_TICKER_STOPWORDS | {"OUSTER"}
    for value in _normalize_list(values):
        for token in re.split(r"[,，、;；()\[\]\s]+", value):
            ticker = _normalize_research_ticker(token)
            if ticker and ticker not in stopwords:
                tickers.append(ticker)
    return sorted(set(tickers))


def _extract_secondary_tickers(text: str, primary: list[str]) -> list[str]:
    primary_set = set(primary)
    tickers = []
    stopwords = RESEARCH_TICKER_STOPWORDS
    for token in re.findall(r"\$?[A-Z]{1,5}\b", text):
        ticker = _normalize_research_ticker(token)
        if ticker and ticker not in primary_set and ticker not in stopwords:
            tickers.append(ticker)
    return sorted(set(tickers))[:8]


def _normalize_research_ticker(token: str) -> str | None:
    raw = str(token or "").strip()
    ticker = normalize_ticker(raw.lstrip("$"))
    if not ticker:
        return None
    # In research prose, single-letter capitals often come from terms like SiC/GaN
    # or sentence fragments. Keep them only when the author used explicit cashtag syntax.
    if len(ticker) == 1 and not raw.startswith("$"):
        return None
    return ticker


def _extract_list_items(text: str, labels: list[str]) -> list[str]:
    result = []
    for line in str(text or "").splitlines():
        lowered = line.lower()
        if any(label.lower() in lowered for label in labels):
            cleaned = re.sub(r"^[^：:]+[：:]\s*", "", line).strip()
            if cleaned:
                result.append(cleaned)
    return result[:5]


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

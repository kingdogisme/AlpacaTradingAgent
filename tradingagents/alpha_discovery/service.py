from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
import json
import re
import time
import uuid
from typing import Any, Protocol

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.integrations.sellthenews import SellTheNewsClient

from .confirmation import ConfirmationConfig, FundamentalDataProvider, MarketDataProvider, apply_confirmations
from .collectors import (
    collect_sellthenews_wsb_analysis,
    collect_sellthenews_wsb_dd,
    merge_candidates,
)
from .models import DiscoveryBatch, DiscoveryEvent, Handoff, OpportunityCandidate, SourceSignal
from .repository import AlphaDiscoveryRepository
from .research_articles import build_candidate_impacts, classify_research_article, enriched_payload
from .symbol_filters import is_common_stock_candidate, normalize_ticker


class GraphRunner(Protocol):
    def run(
        self,
        ticker: str,
        trade_date: str,
        analysts: list[str],
        config_overrides: dict[str, Any] | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        ...


class SecEdgarFundamentalProvider:
    def __init__(self, config: dict):
        self.config = config

    def sec_fundamental_confirmation(self, ticker: str) -> dict:
        from tradingagents.dataflows.sec_edgar_utils import sec_fundamental_confirmation

        return sec_fundamental_confirmation(ticker, config=self.config)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlphaDiscoveryService:
    def __init__(
        self,
        *,
        repository: AlphaDiscoveryRepository | None = None,
        sellthenews_client: SellTheNewsClient | None = None,
        market_data_provider: MarketDataProvider | None = None,
        config: dict | None = None,
    ):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.repository = repository or AlphaDiscoveryRepository(self.config.get("alpha_discovery_db_path"))
        if market_data_provider is not None:
            self.market_data_provider = market_data_provider
        elif _coerce_bool(self.config.get("alpha_discovery_price_volume_confirmation_enabled", False)):
            from .market_data import AlpacaPriceVolumeProvider

            self.market_data_provider = AlpacaPriceVolumeProvider(
                max_bar_age_days=int(self.config.get("alpha_discovery_price_volume_max_bar_age_days", 5))
            )
        else:
            self.market_data_provider = None
        self.fundamental_data_provider: FundamentalDataProvider | None = (
            SecEdgarFundamentalProvider(self.config)
            if _coerce_bool(self.config.get("alpha_discovery_sec_confirmation_enabled", False))
            and _coerce_bool(self.config.get("sec_edgar_enabled", True))
            else None
        )
        self._event_context_batch_id: str | None = None
        self.sellthenews_client = sellthenews_client or SellTheNewsClient(
            self.config.get("sellthenews_base_url", "https://mcp.sellthenews.org/mcp"),
            float(self.config.get("sellthenews_timeout_seconds", 8)),
        )
        self.sellthenews_client = _ObservedSellTheNewsClient(self.sellthenews_client, self)

    def discover(self, *, sources: list[str], max_candidates: int = 25) -> dict:
        batch_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        started = time.monotonic()
        generated_at = utc_now_iso()
        batch = DiscoveryBatch(
            batch_id=batch_id,
            source=",".join(sources),
            generated_at=generated_at,
            config_json={
                "sources": sources,
                "max_candidates": max_candidates,
                "collector": "alpha_discovery_v1",
            },
        )
        self.repository.upsert_batch(batch)
        self._record_event(
            "discover_start",
            batch_id=batch_id,
            source=",".join(sources),
            payload={"sources": sources, "max_candidates": max_candidates},
        )
        candidates = []
        previous_batch_context = self._event_context_batch_id
        self._event_context_batch_id = batch_id
        try:
            if "wsb" in sources:
                candidates.extend(
                    self._run_collector(
                        batch_id=batch_id,
                        source="sellthenews_wsb_analysis",
                        collector=lambda: collect_sellthenews_wsb_analysis(
                            self.sellthenews_client,
                            batch_id=batch_id,
                            top_sectors=int(self.config.get("alpha_discovery_wsb_top_sectors", 10)),
                            per_sector=int(self.config.get("alpha_discovery_wsb_per_sector", 1)),
                        ),
                    )
                )
            if "dd" in sources:
                candidates.extend(
                    self._run_collector(
                        batch_id=batch_id,
                        source="sellthenews_wsb_dd",
                        collector=lambda: collect_sellthenews_wsb_dd(
                            self.sellthenews_client,
                            batch_id=batch_id,
                            limit=int(self.config.get("alpha_discovery_dd_list_limit", 20)),
                            max_posts=int(self.config.get("sellthenews_dd_max_posts", 3)),
                            min_score=int(self.config.get("sellthenews_dd_min_score", 0)),
                            min_comments=int(self.config.get("sellthenews_dd_min_comments", 0)),
                        ),
                    )
                )

            raw_count = len(candidates)
            candidates = merge_candidates(candidates)
            self._record_event(
                "dedupe_complete",
                batch_id=batch_id,
                payload={"raw_count": raw_count, "deduped_count": len(candidates)},
            )
            if _coerce_bool(self.config.get("alpha_discovery_confirmation_enabled", True)):
                candidates = self._apply_confirmations_with_events(candidates, batch_id=batch_id)
            candidates = sorted(candidates, key=lambda item: item.alpha_score, reverse=True)[:max_candidates]
            self.repository.upsert_candidates(candidates, updated_at=generated_at)
            invalidated = self.invalidate_current_basket(updated_at=generated_at)
            superseded_count = self.repository.mark_older_open_candidates_superseded(updated_at=generated_at)
            if invalidated or superseded_count:
                self._record_event(
                    "basket_housekeeping",
                    batch_id=batch_id,
                    status="ok",
                    payload={"invalidated": invalidated, "superseded": superseded_count},
                )
            for candidate in candidates:
                self._record_candidate_event(batch_id, candidate)

            counts = {"A": 0, "B": 0, "C": 0, "Rejected": 0}
            for candidate in candidates:
                counts[candidate.tier] = counts.get(candidate.tier, 0) + 1
            rejection_reasons: dict[str, int] = {}
            for candidate in candidates:
                if candidate.rejected_reason:
                    rejection_reasons[candidate.rejected_reason] = rejection_reasons.get(candidate.rejected_reason, 0) + 1
            summary = {
                "batch_id": batch_id,
                "raw_discoveries": len(candidates),
                "tier_counts": counts,
                "top_rejection_reasons": dict(
                    sorted(rejection_reasons.items(), key=lambda item: item[1], reverse=True)[:5]
                ),
                "candidates": candidates,
            }
            self.repository.update_batch_status(batch_id, "completed")
            self._record_event(
                "discover_complete",
                batch_id=batch_id,
                status="ok",
                payload={key: value for key, value in summary.items() if key != "candidates"},
                duration_ms=_duration_ms(started),
            )
            return summary
        except Exception as exc:
            self.repository.update_batch_status(batch_id, "failed")
            self._record_event(
                "discover_failed",
                batch_id=batch_id,
                status="error",
                message=str(exc),
                payload={"error_type": type(exc).__name__},
                duration_ms=_duration_ms(started),
            )
            raise
        finally:
            self._event_context_batch_id = previous_batch_context

    def ingest_external_candidates(
        self,
        payloads: list[dict[str, Any]],
        *,
        source: str = "n8n_watchlist",
        max_candidates: int | None = None,
    ) -> dict:
        batch_id = f"ingest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        started = time.monotonic()
        generated_at = utc_now_iso()
        batch = DiscoveryBatch(
            batch_id=batch_id,
            source=source,
            generated_at=generated_at,
            config_json={
                "source": source,
                "payload_count": len(payloads),
                "collector": "external_ingest_v1",
            },
        )
        self.repository.upsert_batch(batch)
        self._record_event(
            "external_ingest_start",
            batch_id=batch_id,
            source=source,
            payload={"payload_count": len(payloads), "max_candidates": max_candidates},
        )
        candidates: list[OpportunityCandidate] = []
        skipped: list[dict[str, str]] = []
        for index, payload in enumerate(payloads):
            ticker = normalize_ticker(str(payload.get("ticker") or ""))
            context = " ".join(
                str(part or "")
                for part in (
                    payload.get("theme"),
                    payload.get("catalyst"),
                    payload.get("run_reason"),
                    payload.get("evidence_summary"),
                )
            )
            if not ticker:
                skipped.append({"index": str(index), "reason": "missing_ticker"})
                continue
            if not is_common_stock_candidate(ticker, context=context):
                skipped.append({"ticker": ticker, "reason": "symbol_filter"})
                self._record_event(
                    "external_ingest_skipped",
                    batch_id=batch_id,
                    ticker=ticker,
                    source=source,
                    status="rejected",
                    payload={"reason": "symbol_filter", "index": index},
                )
                continue
            candidate = _candidate_from_external_payload(batch_id=batch_id, source=source, payload=payload, index=index)
            candidates.append(candidate)

        if max_candidates is not None:
            candidates = sorted(candidates, key=lambda item: item.alpha_score, reverse=True)[:max_candidates]
        candidates = merge_candidates(candidates)
        self.repository.upsert_candidates(candidates, updated_at=generated_at)
        invalidated = self.invalidate_current_basket(updated_at=generated_at)
        superseded_count = self.repository.mark_older_open_candidates_superseded(updated_at=generated_at)
        if invalidated or superseded_count:
            self._record_event(
                "basket_housekeeping",
                batch_id=batch_id,
                status="ok",
                payload={"invalidated": invalidated, "superseded": superseded_count},
            )
        for candidate in candidates:
            self._record_candidate_event(batch_id, candidate, event_type="external_candidate")
        summary = {
            "batch_id": batch_id,
            "source": source,
            "accepted": len(candidates),
            "skipped": skipped,
            "tickers": [candidate.ticker for candidate in candidates],
            "tier_counts": _candidate_summary(candidates)["tier_counts"],
            "candidates": candidates,
        }
        self.repository.update_batch_status(batch_id, "completed")
        self._record_event(
            "external_ingest_complete",
            batch_id=batch_id,
            source=source,
            status="ok",
            payload={key: value for key, value in summary.items() if key != "candidates"},
            duration_ms=_duration_ms(started),
        )
        return summary

    def ingest_n8n_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("event_type") != "substack.feed_item.discovered":
            raise ValueError("unsupported event_type")
        article = event.get("article") or {}
        source = event.get("source") or {}
        analysis = event.get("analysis") or {}
        canonical_url = str(article.get("canonical_url") or "")
        if not canonical_url:
            raise ValueError("article.canonical_url is required")

        source_quality_map = _json_config(self.config.get("alpha_discovery_research_source_quality_json"))
        evidence = classify_research_article(event, source_quality_map=source_quality_map)
        impacts = build_candidate_impacts(
            evidence,
            boost_max=float(self.config.get("alpha_discovery_research_boost_max", 0.24)),
            single_article_a_gate=_coerce_bool(self.config.get("alpha_discovery_research_single_article_a_gate", True)),
        )
        tickers = sorted({impact.ticker for impact in impacts if impact.role == "primary"})
        companies = _extract_companies(analysis.get("companies_or_tickers") or [])
        themes = _extract_themes(article.get("title"), analysis.get("summary_zh"), analysis.get("watch_items"))
        enriched = {
            "tickers": tickers,
            "companies": companies,
            "themes": themes,
            "priority_score": _priority_score(tickers=tickers, themes=themes, watch_items=analysis.get("watch_items")),
            **enriched_payload(evidence, impacts),
        }
        received_at = utc_now_iso()
        deduped, stored_event_id = self.repository.upsert_n8n_ingest_event(
            event=event,
            enriched=enriched,
            received_at=received_at,
        )
        if not deduped and _coerce_bool(self.config.get("alpha_discovery_research_boost_enabled", True)):
            self._apply_research_article_impacts(
                event=event,
                evidence=evidence,
                impacts=impacts,
                stored_event_id=stored_event_id,
                received_at=received_at,
            )
        self._record_event(
            "n8n_ingest_event",
            batch_id=event.get("run_id"),
            source=source.get("id") or source.get("name"),
            status="deduped" if deduped else "ok",
            payload={
                "event_id": stored_event_id,
                "canonical_url": canonical_url,
                "title": article.get("title"),
                "enriched": enriched,
            },
        )
        return {
            "status": "accepted",
            "alpha_item_id": f"ad_item_{stored_event_id[:16]}",
            "deduped": deduped,
            "enriched": enriched,
        }

    def _apply_research_article_impacts(
        self,
        *,
        event: dict[str, Any],
        evidence,
        impacts,
        stored_event_id: str,
        received_at: str,
    ) -> None:
        source = event.get("source") or {}
        article = event.get("article") or {}
        batch_id = str(event.get("run_id") or f"n8n-{received_at}")
        self.repository.ensure_batch(
            DiscoveryBatch(
                batch_id=batch_id,
                source=str(source.get("id") or source.get("name") or "n8n_research"),
                generated_at=received_at,
                config_json={"collector": "n8n_research_article_v1", "event_id": stored_event_id},
                status="completed",
            )
        )
        for impact in impacts:
            if not impact.ticker or not is_common_stock_candidate(impact.ticker, context=article.get("title") or ""):
                continue
            existing = self.repository.get_candidate_by_ticker(impact.ticker, status="open")
            candidate = _candidate_from_research_impact(
                batch_id=batch_id,
                event=event,
                evidence=evidence,
                impact=impact,
                existing=existing,
                stored_event_id=stored_event_id,
                received_at=received_at,
            )
            self.repository.upsert_candidate(candidate, updated_at=received_at)
            self._record_candidate_event(batch_id, candidate, event_type="research_article_candidate")

    def invalidate_current_basket(self, *, updated_at: str | None = None) -> int:
        updated_at = updated_at or utc_now_iso()
        rows = self.repository.list_candidates(tiers=None, status="open", limit=None)
        invalidated = 0
        for row in rows:
            context = " ".join(str(part or "") for part in (row.get("theme"), row.get("catalyst"), row.get("run_reason")))
            if is_common_stock_candidate(row["ticker"], context=context):
                continue
            components = dict(row.get("score_components") or {})
            components["promotion_gate"] = "invalidated_symbol_filter"
            risk_flags = sorted(set((row.get("risk_flags") or []) + ["invalid_symbol_filter"]))
            self.repository.update_candidate_status(
                row["candidate_id"],
                status="invalidated",
                cooldown_state="invalidated",
                score_components=components,
                risk_flags=risk_flags,
                updated_at=updated_at,
            )
            self._record_event(
                "candidate_invalidated",
                candidate_id=row["candidate_id"],
                ticker=row["ticker"],
                status="invalidated",
                payload={"previous_tier": row.get("tier"), "reason": "symbol_filter", "theme": row.get("theme")},
            )
            invalidated += 1
        return invalidated

    def promote_existing(self, *, tiers: list[str] | None = None, max_candidates: int = 25) -> dict:
        started = time.monotonic()
        batch_id = f"confirm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        self._record_event(
            "confirm_start",
            batch_id=batch_id,
            payload={"tiers": tiers, "max_candidates": max_candidates},
        )
        previous_batch_context = self._event_context_batch_id
        self._event_context_batch_id = batch_id
        try:
            rows = self.repository.list_candidates(tiers=tiers, status="open", limit=max_candidates)
            candidates = [_candidate_from_row(row) for row in rows]
            for candidate in candidates:
                candidate.source_signals = self.repository.get_source_signals(candidate.candidate_id)
            if _coerce_bool(self.config.get("alpha_discovery_confirmation_enabled", True)):
                self._apply_confirmations_with_events(candidates, batch_id=batch_id)
            updated_at = utc_now_iso()
            self.repository.upsert_candidates(candidates, updated_at=updated_at)
            for candidate in candidates:
                self._record_candidate_event(batch_id, candidate, event_type="confirm_candidate")
            summary = _candidate_summary(candidates)
            summary["batch_id"] = batch_id
            self._record_event(
                "confirm_complete",
                batch_id=batch_id,
                status="ok",
                payload=summary,
                duration_ms=_duration_ms(started),
            )
            return summary
        except Exception as exc:
            self._record_event(
                "confirm_failed",
                batch_id=batch_id,
                status="error",
                message=str(exc),
                payload={"error_type": type(exc).__name__},
                duration_ms=_duration_ms(started),
            )
            raise
        finally:
            self._event_context_batch_id = previous_batch_context

    def list_candidates(
        self,
        *,
        tiers: list[str] | None = None,
        status: str | None = "open",
        limit: int | None = None,
        ticker: str | None = None,
    ) -> list[dict]:
        return self.repository.list_candidates(tiers=tiers, status=status, limit=limit, ticker=ticker)

    def basket_report(self, *, status: str | None = "open") -> dict:
        rows = self.repository.list_candidates(tiers=None, status=status, limit=None)
        signals = self.repository.list_source_signals(candidate_ids=[row["candidate_id"] for row in rows])
        lifecycle_by_candidate = self._lifecycle_by_candidate(rows)
        signal_counts_by_candidate: dict[str, int] = {}
        raw_sources_by_candidate: dict[str, set[str]] = {}
        for signal in signals:
            candidate_id = signal["candidate_id"]
            signal_counts_by_candidate[candidate_id] = signal_counts_by_candidate.get(candidate_id, 0) + 1
            raw_sources_by_candidate.setdefault(candidate_id, set()).add(signal["source"])
        summary = {
            "total": len(rows),
            "by_tier": {},
            "by_source": {},
            "by_raw_source": {},
            "by_theme": {},
            "by_ticker": {},
            "confirmation_coverage": {},
            "source_hit_rates": {},
            "theme_hit_rates": {},
            "top_rejection_reasons": {},
        }
        confirmed_rows = 0
        for row in rows:
            summary["by_tier"][row["tier"]] = summary["by_tier"].get(row["tier"], 0) + 1
            if row.get("theme"):
                summary["by_theme"][row["theme"]] = summary["by_theme"].get(row["theme"], 0) + 1
            summary["by_ticker"][row["ticker"]] = {
                "tier": row["tier"],
                "alpha_score": row["alpha_score"],
                "opportunity_type": row["opportunity_type"],
                "theme": row.get("theme"),
                "confirmation_sources": row.get("score_components", {}).get("confirmation_sources", []),
                "promotion_gate": row.get("score_components", {}).get("promotion_gate"),
                "source_signal_count": signal_counts_by_candidate.get(row["candidate_id"], 0),
                "raw_sources": sorted(raw_sources_by_candidate.get(row["candidate_id"], set())),
                "risk_flags": row.get("risk_flags", []),
                "lifecycle": lifecycle_by_candidate.get(row["candidate_id"], {}),
            }
            if row.get("rejected_reason"):
                reason = row["rejected_reason"]
                summary["top_rejection_reasons"][reason] = summary["top_rejection_reasons"].get(reason, 0) + 1
            sources = row.get("score_components", {}).get("confirmation_sources", [])
            if sources:
                confirmed_rows += 1
            for source in sources:
                summary["by_source"][source] = summary["by_source"].get(source, 0) + 1
            for source in raw_sources_by_candidate.get(row["candidate_id"], set()):
                summary["by_raw_source"][source] = summary["by_raw_source"].get(source, 0) + 1
        summary["confirmation_coverage"] = {
            "confirmed_candidates": confirmed_rows,
            "unconfirmed_candidates": len(rows) - confirmed_rows,
            "confirmed_ratio": round(confirmed_rows / len(rows), 3) if rows else 0.0,
        }
        outcome_rows = self.repository.list_outcomes(status=status)
        summary["source_hit_rates"] = _hit_rate_report(outcome_rows, group_by="source")
        summary["theme_hit_rates"] = _hit_rate_report(outcome_rows, group_by="theme")
        return summary

    def _lifecycle_by_candidate(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        candidate_ids = [row["candidate_id"] for row in rows]
        if not candidate_ids:
            return {}
        handoffs = self.repository.list_handoffs(candidate_ids=candidate_ids, limit=None)
        latest_handoff_by_candidate: dict[str, dict[str, Any]] = {}
        for handoff in handoffs:
            latest_handoff_by_candidate.setdefault(handoff["candidate_id"], handoff)
        plan_by_run_id: dict[str, Any] = {}
        try:
            from tradingagents.trade_lifecycle import TradePlanRepository
            from tradingagents.trade_lifecycle.reporting import summarize_plan

            plan_repository = TradePlanRepository(self.config.get("trade_lifecycle_db_path"))
            run_ids = [handoff.get("run_id") for handoff in handoffs if handoff.get("run_id")]
            for run_id in run_ids:
                plan = plan_repository.get_plan_by_source_run_id(run_id)
                if plan:
                    plan_by_run_id[run_id] = summarize_plan(plan, plan_repository)
        except Exception:
            plan_by_run_id = {}
        result: dict[str, dict[str, Any]] = {}
        for candidate_id, handoff in latest_handoff_by_candidate.items():
            plan_summary = plan_by_run_id.get(handoff.get("run_id"))
            result[candidate_id] = {
                "run_id": handoff.get("run_id"),
                "handoff_status": handoff.get("status"),
                "ata_final_signal": handoff.get("ata_final_signal"),
                "ata_confidence": handoff.get("ata_confidence"),
                "plan_id": handoff.get("plan_id") or (plan_summary or {}).get("plan_id"),
                "plan_status": (plan_summary or {}).get("status"),
                "plan_progress": (plan_summary or {}).get("progress"),
                "latest_validation": (plan_summary or {}).get("latest_validation"),
                "latest_event": (plan_summary or {}).get("latest_event"),
            }
        return result

    def health_report(self) -> dict:
        events = self.repository.list_events(limit=500)
        batches = self.repository.list_batches(limit=10)
        candidates = self.repository.list_candidates(tiers=None, status="open", limit=None)
        handoffs_today = self.repository.recent_handoffs_all(
            since_iso=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        )
        errors = [event for event in events if event.get("status") == "error"]
        recent_event_types: dict[str, int] = {}
        for event in events:
            event_type = str(event.get("event_type") or "unknown")
            recent_event_types[event_type] = recent_event_types.get(event_type, 0) + 1
        by_tier: dict[str, int] = {}
        for candidate in candidates:
            tier = str(candidate.get("tier") or "unknown")
            by_tier[tier] = by_tier.get(tier, 0) + 1
        return {
            "status": "degraded" if errors else "ok",
            "db_path": str(self.repository.path),
            "latest_batches": batches,
            "open_candidates": {
                "total": len(candidates),
                "by_tier": by_tier,
            },
            "handoffs_today": len(handoffs_today),
            "recent_event_counts": recent_event_types,
            "recent_errors": errors[:20],
        }

    def run_candidates(
        self,
        *,
        tier: str = "A",
        max_symbols: int = 6,
        execute: bool = False,
        trade_date: str | None = None,
        graph_runner: GraphRunner | None = None,
        ticker: str | None = None,
    ) -> list[dict]:
        daily_limit = int(self.config.get("alpha_discovery_max_full_ata_runs_per_day", 2))
        daily_budget = int(self.config.get("alpha_discovery_default_ata_daily_budget", max_symbols))
        candidates = self.repository.list_candidates(
            tiers=[tier],
            status="open",
            limit=max_symbols * 3,
            ticker=ticker,
        )
        results = []
        now = datetime.now(timezone.utc)
        cooldown_hours = float(self.config.get("alpha_discovery_full_ata_cooldown_hours", 6))
        since_iso = (now - timedelta(hours=cooldown_hours)).isoformat()
        day_start_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        total_today_runs = self.repository.recent_handoffs_all(since_iso=day_start_iso)
        self._record_event(
            "run_start",
            payload={
                "tier": tier,
                "max_symbols": max_symbols,
                "execute": execute,
                "daily_budget": daily_budget,
                "same_ticker_daily_limit": daily_limit,
            },
        )

        for candidate in candidates:
            if len([row for row in results if row.get("run_status") in {"dry_run", "executed"}]) >= max_symbols:
                break
            if execute and len(total_today_runs) >= daily_budget:
                self._record_run_decision(candidate, "daily_budget", execute=False)
                results.append({**candidate, "run_status": "daily_budget", "execute": False})
                continue
            recent = self.repository.recent_handoffs(candidate["ticker"], since_iso=since_iso)
            if recent:
                self._record_run_decision(candidate, "cooldown", execute=False, payload={"recent_handoffs": len(recent)})
                results.append({**candidate, "run_status": "cooldown", "execute": False})
                continue
            today_runs = self.repository.recent_handoffs(candidate["ticker"], since_iso=day_start_iso)
            if len(today_runs) >= daily_limit:
                self._record_run_decision(candidate, "daily_limit", execute=False, payload={"today_runs": len(today_runs)})
                results.append({**candidate, "run_status": "daily_limit", "execute": False})
                continue
            analysts = self._default_ata_analysts()
            ata_config = self._ata_config_for_candidate(candidate)
            if not execute:
                self._record_run_decision(
                    candidate,
                    "dry_run",
                    execute=False,
                    payload={"analysts": analysts, "ata_config": ata_config},
                )
                results.append({**candidate, "run_status": "dry_run", "execute": False, "ata_config": ata_config})
                continue
            if graph_runner is None:
                raise ValueError("graph_runner is required when execute=True")
            run_result = graph_runner.run(
                candidate["ticker"],
                trade_date or datetime.now().date().isoformat(),
                analysts,
                ata_config,
            )
            if len(run_result) == 4:
                run_id, final_signal, confidence, plan_id = run_result
            else:
                run_id, final_signal, confidence = run_result
                plan_id = self._plan_id_for_run(run_id)
            self.repository.upsert_handoff(
                Handoff(
                    candidate_id=candidate["candidate_id"],
                    run_id=run_id or f"missing-run-id-{uuid.uuid4().hex[:8]}",
                    status="completed" if final_signal else "unknown",
                    executed_at=utc_now_iso(),
                    ata_final_signal=final_signal,
                    ata_confidence=confidence,
                    plan_id=plan_id,
                )
            )
            total_today_runs.append({"candidate_id": candidate["candidate_id"], "ticker": candidate["ticker"]})
            self._record_run_decision(
                candidate,
                "executed",
                execute=True,
                payload={
                    "run_id": run_id,
                    "plan_id": plan_id,
                    "ata_final_signal": final_signal,
                    "analysts": analysts,
                    "ata_config": ata_config,
                },
            )
            results.append(
                {
                    **candidate,
                    "run_status": "executed",
                    "execute": True,
                    "run_id": run_id,
                    "plan_id": plan_id,
                    "ata_final_signal": final_signal,
                    "ata_config": ata_config,
                }
            )
        return results

    def _plan_id_for_run(self, run_id: str | None) -> str | None:
        if not run_id:
            return None
        try:
            from tradingagents.trade_lifecycle import TradePlanRepository

            plan = TradePlanRepository(self.config.get("trade_lifecycle_db_path")).get_plan_by_source_run_id(run_id)
            return plan.plan_id if plan else None
        except Exception:
            return None

    def _default_ata_analysts(self) -> list[str]:
        raw = self.config.get("alpha_discovery_ata_analysts") or "market,fundamentals,news,social,macro"
        if isinstance(raw, str):
            analysts = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(raw, list):
            analysts = [str(part).strip() for part in raw if str(part).strip()]
        else:
            analysts = []
        return analysts or ["market", "fundamentals", "news", "social", "macro"]

    def _ata_config_for_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "trading_horizon": self.config.get("alpha_discovery_ata_horizon", "position"),
            "trading_mode": self.config.get("alpha_discovery_ata_trading_mode", "investment"),
            "episode_ledger_metadata": {
                "source": "alpha_discovery",
                "ad_candidate_id": candidate.get("candidate_id"),
                "ad_batch_id": candidate.get("batch_id"),
                "ad_tier": candidate.get("tier"),
                "ad_alpha_score": candidate.get("alpha_score"),
                "ad_opportunity_type": candidate.get("opportunity_type"),
                "ad_direction_hint": candidate.get("direction_hint"),
            },
        }

    def _run_collector(self, *, batch_id: str, source: str, collector) -> list[OpportunityCandidate]:
        collector_started = time.monotonic()
        self._record_event("collector_start", batch_id=batch_id, source=source)
        try:
            candidates = collector()
        except Exception as exc:
            self._record_event(
                "collector_failed",
                batch_id=batch_id,
                source=source,
                status="error",
                message=str(exc),
                payload={"error_type": type(exc).__name__},
                duration_ms=_duration_ms(collector_started),
            )
            if _coerce_bool(self.config.get("alpha_discovery_soft_fail_collectors", True)):
                return []
            raise
        self._record_event(
            "collector_complete",
            batch_id=batch_id,
            source=source,
            status="ok",
            payload={"candidate_count": len(candidates)},
            duration_ms=_duration_ms(collector_started),
        )
        return candidates

    def _apply_confirmations_with_events(
        self,
        candidates: list[OpportunityCandidate],
        *,
        batch_id: str,
    ) -> list[OpportunityCandidate]:
        confirmation_started = time.monotonic()
        self._record_event("confirmation_start", batch_id=batch_id, payload={"candidate_count": len(candidates)})
        candidates = apply_confirmations(
            candidates,
            client=self.sellthenews_client,
            market_data_provider=self.market_data_provider,
            fundamental_data_provider=self.fundamental_data_provider,
            config=ConfirmationConfig(
                news_enabled=_coerce_bool(self.config.get("alpha_discovery_news_confirmation_enabled", True)),
                search_news_enabled=_coerce_bool(self.config.get("alpha_discovery_search_news_confirmation_enabled", False)),
                live_news_enabled=_coerce_bool(self.config.get("alpha_discovery_live_news_confirmation_enabled", False)),
                policy_social_enabled=_coerce_bool(self.config.get("alpha_discovery_policy_social_confirmation_enabled", False)),
                options_enabled=_coerce_bool(self.config.get("alpha_discovery_options_confirmation_enabled", False)),
                price_volume_enabled=_coerce_bool(self.config.get("alpha_discovery_price_volume_confirmation_enabled", False)),
                sec_fundamental_enabled=_coerce_bool(self.config.get("alpha_discovery_sec_confirmation_enabled", False)),
                min_confirmations_for_a=int(self.config.get("alpha_discovery_min_confirmations_for_a", 1)),
                min_confirmations_for_dd_a=int(self.config.get("alpha_discovery_min_confirmations_for_dd_a", 2)),
                news_max_age_days=int(self.config.get("alpha_discovery_news_confirmation_max_age_days", 14)),
                require_news_date=_coerce_bool(self.config.get("alpha_discovery_require_news_confirmation_date", True)),
            ),
        )
        self._record_event(
            "confirmation_complete",
            batch_id=batch_id,
            status="ok",
            payload=_candidate_summary(candidates),
            duration_ms=_duration_ms(confirmation_started),
        )
        return candidates

    def list_events(
        self,
        *,
        batch_id: str | None = None,
        candidate_id: str | None = None,
        event_type: str | None = None,
        status: str | None = None,
        limit: int | None = 100,
    ) -> list[dict]:
        return self.repository.list_events(
            batch_id=batch_id,
            candidate_id=candidate_id,
            event_type=event_type,
            status=status,
            limit=limit,
        )

    def evaluation_report(self, *, status: str | None = "open") -> dict:
        outcomes = self.repository.list_outcomes(status=status)
        rows = self.repository.list_candidates(tiers=None, status=status, limit=None)
        by_candidate = {row["candidate_id"]: row for row in rows}
        handoffs = self.repository.recent_handoffs_all(since_iso="0000-01-01T00:00:00Z")
        handoff_by_candidate: dict[str, list[dict]] = {}
        for handoff in handoffs:
            handoff_by_candidate.setdefault(handoff["candidate_id"], []).append(handoff)

        confusion = {
            "ad_selected_ata_bullish_alpha_positive": 0,
            "ad_selected_ata_bullish_alpha_negative": 0,
            "ad_selected_ata_rejected_alpha_positive": 0,
            "ad_selected_ata_rejected_alpha_negative": 0,
            "shadow_A_alpha_positive": 0,
            "shadow_A_alpha_negative": 0,
            "shadow_B_alpha_positive": 0,
            "shadow_B_alpha_negative": 0,
            "shadow_C_alpha_positive": 0,
            "shadow_C_alpha_negative": 0,
            "shadow_Rejected_alpha_positive": 0,
            "shadow_Rejected_alpha_negative": 0,
            "shadow_unknown_alpha_positive": 0,
            "shadow_unknown_alpha_negative": 0,
        }
        actual_performance = {
            "alpha_positive": [],
            "alpha_negative": [],
        }
        by_opportunity_type: dict[str, dict[str, int]] = {}
        for outcome in outcomes:
            if int(outcome["horizon_days"]) != 3 or outcome.get("alpha_return") is None:
                continue
            candidate = by_candidate.get(outcome["candidate_id"], {})
            opportunity_type = str(candidate.get("opportunity_type") or outcome.get("opportunity_type") or "unknown")
            bucket = by_opportunity_type.setdefault(opportunity_type, {key: 0 for key in confusion})
            positive = float(outcome["alpha_return"]) > 0
            candidate_handoffs = handoff_by_candidate.get(outcome["candidate_id"], [])
            if candidate_handoffs:
                signal = str(candidate_handoffs[0].get("ata_final_signal") or "").upper()
                bullish = signal in {"BUY", "LONG"}
                key = (
                    "ad_selected_ata_bullish_alpha_positive"
                    if bullish and positive
                    else "ad_selected_ata_bullish_alpha_negative"
                    if bullish
                    else "ad_selected_ata_rejected_alpha_positive"
                    if positive
                    else "ad_selected_ata_rejected_alpha_negative"
                )
            else:
                tier = _normalize_shadow_tier(str(candidate.get("tier") or outcome.get("tier") or "unknown"))
                key = f"shadow_{tier}_{'alpha_positive' if positive else 'alpha_negative'}"
            confusion[key] += 1
            bucket[key] += 1
            actual_performance["alpha_positive" if positive else "alpha_negative"].append(
                {
                    "candidate_id": outcome["candidate_id"],
                    "ticker": candidate.get("ticker") or outcome.get("ticker"),
                    "tier_at_discovery": candidate.get("tier") or outcome.get("tier"),
                    "opportunity_type": opportunity_type,
                    "alpha_return": outcome.get("alpha_return"),
                    "raw_return": outcome.get("raw_return"),
                    "benchmark_return": outcome.get("benchmark_return"),
                    "had_ata_handoff": bool(candidate_handoffs),
                    "ata_final_signal": candidate_handoffs[0].get("ata_final_signal") if candidate_handoffs else None,
                }
            )

        return {
            "horizon_days": 3,
            "confusion_matrix": confusion,
            "by_opportunity_type": by_opportunity_type,
            "actual_performance": actual_performance,
            "source_hit_rates": _hit_rate_report(outcomes, group_by="source"),
            "theme_hit_rates": _hit_rate_report(outcomes, group_by="theme"),
        }

    def _record_event(
        self,
        event_type: str,
        *,
        batch_id: str | None = None,
        candidate_id: str | None = None,
        ticker: str | None = None,
        source: str | None = None,
        status: str = "info",
        message: str | None = None,
        payload: dict | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.repository.insert_event(
            DiscoveryEvent(
                event_id=None,
                event_time=utc_now_iso(),
                event_type=event_type,
                batch_id=batch_id,
                candidate_id=candidate_id,
                ticker=ticker,
                source=source,
                status=status,
                message=message,
                payload_json=payload or {},
                duration_ms=duration_ms,
            )
        )

    def _record_candidate_event(
        self,
        batch_id: str,
        candidate: OpportunityCandidate,
        *,
        event_type: str = "score_candidate",
    ) -> None:
        self._record_event(
            event_type,
            batch_id=batch_id,
            candidate_id=candidate.candidate_id,
            ticker=candidate.ticker,
            status="rejected" if candidate.tier == "Rejected" else "ok",
            payload={
                "tier": candidate.tier,
                "alpha_score": candidate.alpha_score,
                "opportunity_type": candidate.opportunity_type,
                "promotion_gate": (candidate.score_components or {}).get("promotion_gate"),
                "confirmation_sources": (candidate.score_components or {}).get("confirmation_sources", []),
                "risk_flags": candidate.risk_flags,
                "rejected_reason": candidate.rejected_reason,
            },
        )

    def _record_run_decision(
        self,
        candidate: dict,
        run_status: str,
        *,
        execute: bool,
        payload: dict | None = None,
    ) -> None:
        self._record_event(
            "run_decision",
            candidate_id=candidate.get("candidate_id"),
            ticker=candidate.get("ticker"),
            status=run_status,
            payload={
                "execute": execute,
                "tier": candidate.get("tier"),
                "alpha_score": candidate.get("alpha_score"),
                "promotion_gate": (candidate.get("score_components") or {}).get("promotion_gate"),
                **(payload or {}),
            },
        )


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _json_config(value) -> dict[str, float]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_tickers(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = [values]
    result = []
    for value in values:
        for token in re.split(r"[,，、;；\s]+", str(value or "")):
            token = token.strip().upper().lstrip("$")
            if 1 <= len(token) <= 5 and token.isalpha() and token not in {"AI", "CEO", "GPU", "IPO"}:
                result.append(token)
    return sorted(set(result))


def _extract_companies(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = [values]
    companies = []
    for value in values:
        text = str(value or "").strip()
        if text and not re.fullmatch(r"\$?[A-Za-z]{1,5}", text):
            companies.append(text)
    return companies[:10]


def _extract_themes(*parts: Any) -> list[str]:
    text = " ".join(str(part or "").lower() for part in parts)
    mapping = {
        "advanced_packaging": ["advanced packaging", "先进封装", "cowos", "soic"],
        "physical_ai": ["physical ai", "物理ai", "lidar", "ouster"],
        "semiconductors": ["semis", "semiconductor", "半导体", "gpu", "芯片"],
        "space": ["spacex", "space"],
        "crypto_fintech": ["crypto", "stablecoin", "crcl", "加密"],
        "defense": ["defense", "dpa", "国防"],
        "ai_infrastructure": ["ai", "datacenter", "数据中心", "光互连"],
    }
    themes = [theme for theme, needles in mapping.items() if any(needle in text for needle in needles)]
    return themes[:6]


def _priority_score(*, tickers: list[str], themes: list[str], watch_items: Any) -> float:
    score = 0.45
    score += min(len(tickers), 3) * 0.08
    score += min(len(themes), 3) * 0.06
    if watch_items:
        score += 0.08
    return round(min(score, 0.95), 3)


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class _ObservedSellTheNewsClient:
    def __init__(self, client, service: AlphaDiscoveryService):
        self._client = client
        self._service = service

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        started = time.monotonic()
        try:
            result = self._client.call_tool(tool_name, arguments)
        except Exception as exc:
            self._service._record_event(
                "mcp_tool_call",
                batch_id=self._service._event_context_batch_id,
                source=f"sellthenews.{tool_name}",
                status="error",
                message=str(exc),
                payload={"tool": tool_name, "args": _redact_tool_args(arguments), "error_type": type(exc).__name__},
                duration_ms=_duration_ms(started),
            )
            raise
        self._service._record_event(
            "mcp_tool_call",
            batch_id=self._service._event_context_batch_id,
            source=f"sellthenews.{tool_name}",
            status="ok",
            payload={"tool": tool_name, "args": _redact_tool_args(arguments), "chars": len(str(result or ""))},
            duration_ms=_duration_ms(started),
        )
        return result

    def __getattr__(self, name: str):
        return getattr(self._client, name)


def _redact_tool_args(arguments: dict) -> dict:
    result = {}
    for key, value in dict(arguments or {}).items():
        if isinstance(value, str) and len(value) > 240:
            result[key] = value[:240] + "...[truncated]"
        else:
            result[key] = value
    return result


def _candidate_from_row(row: dict) -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id=row["candidate_id"],
        batch_id=row["batch_id"],
        ticker=row["ticker"],
        tier=row["tier"],
        alpha_score=float(row["alpha_score"]),
        opportunity_type=row["opportunity_type"],
        direction_hint=row["direction_hint"],
        theme=row.get("theme"),
        catalyst=row.get("catalyst"),
        ttl=row.get("ttl"),
        cooldown_state=row.get("cooldown_state", "eligible"),
        recommended_analysts=row.get("recommended_analysts") or ["market", "social", "news", "macro"],
        run_reason=row.get("run_reason"),
        rejected_reason=row.get("rejected_reason"),
        status=row.get("status", "open"),
        discovered_at=row.get("discovered_at"),
        score_components=row.get("score_components") or {},
        source_signals=[],
        risk_flags=row.get("risk_flags") or [],
    )


def _candidate_from_research_impact(
    *,
    batch_id: str,
    event: dict[str, Any],
    evidence,
    impact,
    existing: dict[str, Any] | None,
    stored_event_id: str,
    received_at: str,
) -> OpportunityCandidate:
    article = event.get("article") or {}
    source = event.get("source") or {}
    base_score = float(existing.get("alpha_score", 0.5) if existing else 0.5)
    alpha_score = round(min(0.99, max(base_score, 0.55) + impact.research_boost), 3)
    existing_tier = existing.get("tier") if existing else "C"
    tier = _promote_tier(existing_tier, impact.max_tier, impact.confirmation)
    components = dict(existing.get("score_components") or {}) if existing else {}
    confirmation_sources = set(components.get("confirmation_sources") or [])
    if impact.confirmation:
        confirmation_sources.add("research_article")
    components.update(
        {
            "research_article_boost": round(float(components.get("research_article_boost", 0.0) or 0.0) + impact.research_boost, 3),
            "research_article_count": int(components.get("research_article_count", 0) or 0) + 1,
            "research_quality_max": max(float(components.get("research_quality_max", 0.0) or 0.0), evidence.evidence_quality),
            "confirmation_sources": sorted(confirmation_sources),
            "promotion_gate": impact.promotion_gate,
        }
    )
    risk_flags = sorted(set((existing.get("risk_flags") or []) if existing else []) | {"research_article_signal"})
    candidate_id = existing.get("candidate_id") if existing else f"{batch_id}-research-{impact.ticker.lower()}"
    signal = SourceSignal(
        candidate_id=candidate_id,
        source="research_article",
        raw_artifact_id=str(article.get("canonical_url") or stored_event_id),
        source_timestamp=str(article.get("published_at") or received_at),
        sentiment=impact.role,
        evidence_json={
            "event_id": stored_event_id,
            "source_id": source.get("id"),
            "source_name": source.get("name"),
            "article_url": article.get("canonical_url"),
            "article_title": article.get("title"),
            "research_article": evidence.asdict(),
            "candidate_impact": impact.asdict(),
        },
    )
    return OpportunityCandidate(
        candidate_id=candidate_id,
        batch_id=existing.get("batch_id") if existing else batch_id,
        ticker=impact.ticker,
        tier=tier,
        alpha_score=alpha_score,
        opportunity_type=existing.get("opportunity_type") if existing else ("second_order" if impact.role == "secondary" else "continuation"),
        direction_hint=evidence.direction_hint if evidence.direction_hint != "unknown" else (existing.get("direction_hint") if existing else "mixed"),
        theme=existing.get("theme") if existing else evidence.article_kind,
        catalyst=article.get("title") or (existing.get("catalyst") if existing else None),
        ttl=existing.get("ttl") if existing else evidence.time_horizon,
        cooldown_state=existing.get("cooldown_state", "eligible") if existing else "eligible",
        recommended_analysts=existing.get("recommended_analysts") if existing else ["market", "news", "fundamentals"],
        run_reason=impact.reason,
        rejected_reason=existing.get("rejected_reason") if existing else None,
        status=existing.get("status", "open") if existing else "open",
        discovered_at=existing.get("discovered_at") if existing else received_at,
        score_components=components,
        source_signals=[signal],
        risk_flags=risk_flags,
    )


def _promote_tier(existing_tier: str | None, max_tier: str, confirmation: bool) -> str:
    if confirmation and max_tier == "A":
        return "A"
    if existing_tier == "A":
        return "A"
    if max_tier in {"A", "B"}:
        return "B"
    return existing_tier or "C"


def _candidate_summary(candidates: list[OpportunityCandidate]) -> dict:
    counts = {"A": 0, "B": 0, "C": 0, "Rejected": 0}
    for candidate in candidates:
        counts[candidate.tier] = counts.get(candidate.tier, 0) + 1
    return {
        "updated_candidates": len(candidates),
        "tier_counts": counts,
        "promoted_to_a": [candidate.ticker for candidate in candidates if candidate.tier == "A"],
    }


def _normalize_shadow_tier(tier: str) -> str:
    normalized = str(tier or "unknown")
    if normalized in {"A", "B", "C", "Rejected"}:
        return normalized
    return "unknown"


def _candidate_id_for_external(batch_id: str, ticker: str, source: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-") or "external"
    return f"{batch_id}-{slug}-{ticker.lower()}-{index}"


def _candidate_from_external_payload(*, batch_id: str, source: str, payload: dict[str, Any], index: int) -> OpportunityCandidate:
    ticker = normalize_ticker(str(payload.get("ticker") or ""))
    tier = str(payload.get("tier") or "B")
    if tier not in {"A", "B", "C", "Rejected"}:
        tier = "B"
    alpha_score = float(payload.get("alpha_score") or payload.get("score") or 0.55)
    direction_hint = str(payload.get("direction_hint") or "mixed")
    opportunity_type = str(payload.get("opportunity_type") or "continuation")
    if opportunity_type not in {"continuation", "reversal", "volatility", "second_order", "avoid"}:
        opportunity_type = "continuation"
    discovered_at = str(payload.get("discovered_at") or utc_now_iso())
    confirmation_sources = payload.get("confirmation_sources") or []
    if not isinstance(confirmation_sources, list):
        confirmation_sources = [str(confirmation_sources)]
    risk_flags = payload.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = [str(risk_flags)]
    recommended_analysts = payload.get("recommended_analysts") or ["market", "social", "news", "macro"]
    if not isinstance(recommended_analysts, list):
        recommended_analysts = [str(recommended_analysts)]
    raw_artifact_id = str(
        payload.get("raw_artifact_id")
        or payload.get("article_url")
        or payload.get("url")
        or f"external://{source}/{ticker}/{index}"
    )
    evidence_json = {
        "headline": payload.get("headline") or payload.get("title"),
        "article_url": payload.get("article_url") or payload.get("url"),
        "published_at": payload.get("published_at"),
        "source_name": payload.get("source_name") or source,
        "evidence_summary": payload.get("evidence_summary"),
        "meta": payload.get("meta") or {},
    }
    source_signal = SourceSignal(
        candidate_id=_candidate_id_for_external(batch_id, ticker, source, index),
        source=str(payload.get("source_signal") or source),
        raw_artifact_id=raw_artifact_id,
        source_timestamp=str(payload.get("published_at") or discovered_at),
        mentions=payload.get("mentions"),
        sentiment=payload.get("sentiment"),
        evidence_json=evidence_json,
    )
    return OpportunityCandidate(
        candidate_id=source_signal.candidate_id,
        batch_id=batch_id,
        ticker=ticker,
        tier=tier,
        alpha_score=round(alpha_score, 3),
        opportunity_type=opportunity_type,
        direction_hint=direction_hint,
        theme=payload.get("theme"),
        catalyst=payload.get("catalyst") or payload.get("evidence_summary") or payload.get("headline") or payload.get("title"),
        ttl=payload.get("ttl"),
        cooldown_state=str(payload.get("cooldown_state") or "eligible"),
        recommended_analysts=[str(item) for item in recommended_analysts],
        run_reason=payload.get("run_reason") or "External watchlist signal ingested into Alpha Discovery.",
        rejected_reason=payload.get("rejected_reason"),
        status=str(payload.get("status") or "open"),
        discovered_at=discovered_at,
        score_components={
            "external_score": round(alpha_score, 3),
            "social_heat": float(payload.get("social_heat") or 0.0),
            "dd_quality": float(payload.get("dd_quality") or 0.0),
            "news_confirmation": float(payload.get("news_confirmation") or 0.0),
            "price_volume_confirmation": float(payload.get("price_volume_confirmation") or 0.0),
            "options_pressure": float(payload.get("options_pressure") or 0.0),
            "crowding_penalty": float(payload.get("crowding_penalty") or 0.0),
            "staleness_penalty": float(payload.get("staleness_penalty") or 0.0),
            "continuation_score": round(alpha_score, 3) if opportunity_type == "continuation" else 0.0,
            "reversal_score": round(alpha_score, 3) if opportunity_type == "reversal" else 0.0,
            "volatility_score": round(alpha_score, 3) if opportunity_type == "volatility" else 0.0,
            "second_order_score": round(alpha_score, 3) if opportunity_type == "second_order" else 0.0,
            "confirmation_sources": [str(item) for item in confirmation_sources],
            "promotion_gate": str(payload.get("promotion_gate") or "external_ingest"),
        },
        source_signals=[source_signal],
        risk_flags=[str(item) for item in risk_flags],
    )


def _hit_rate_report(outcomes: list[dict], *, group_by: str) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in outcomes:
        if group_by == "source":
            groups = row.get("score_components", {}).get("confirmation_sources") or ["unconfirmed"]
        else:
            groups = [row.get(group_by) or "unknown"]
        for group in groups:
            grouped.setdefault(str(group), []).append(row)

    report = {}
    for group, rows in grouped.items():
        horizons = sorted({int(row["horizon_days"]) for row in rows})
        horizon_report = {}
        for horizon in horizons:
            horizon_rows = [row for row in rows if int(row["horizon_days"]) == horizon]
            alpha_values = [row["alpha_return"] for row in horizon_rows if row.get("alpha_return") is not None]
            raw_values = [row["raw_return"] for row in horizon_rows if row.get("raw_return") is not None]
            hits = [value for value in alpha_values if value > 0]
            horizon_report[str(horizon)] = {
                "samples": len(horizon_rows),
                "alpha_samples": len(alpha_values),
                "hit_rate": round(len(hits) / len(alpha_values), 3) if alpha_values else None,
                "avg_alpha_return": round(mean(alpha_values), 5) if alpha_values else None,
                "avg_raw_return": round(mean(raw_values), 5) if raw_values else None,
            }
        report[group] = horizon_report
    return report

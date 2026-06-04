from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterable

from tradingagents.default_config import DEFAULT_CONFIG

from .models import DiscoveryBatch, DiscoveryEvent, Handoff, OpportunityCandidate, Outcome, SourceSignal


def default_alpha_discovery_path() -> Path:
    return Path(
        DEFAULT_CONFIG.get(
            "alpha_discovery_db_path",
            "~/.tradingagents/alpha_discovery/alpha_discovery.sqlite",
        )
    ).expanduser()


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, ensure_ascii=False)


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


class AlphaDiscoveryRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else default_alpha_discovery_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS discovery_batches (
                    batch_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_batches_source_time
                    ON discovery_batches(source, generated_at);

                CREATE TABLE IF NOT EXISTS opportunity_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    alpha_score REAL NOT NULL,
                    opportunity_type TEXT NOT NULL,
                    direction_hint TEXT NOT NULL,
                    theme TEXT,
                    catalyst TEXT,
                    ttl TEXT,
                    cooldown_state TEXT NOT NULL,
                    recommended_analysts_json TEXT NOT NULL,
                    run_reason TEXT,
                    rejected_reason TEXT,
                    status TEXT NOT NULL,
                    discovered_at TEXT,
                    score_components_json TEXT NOT NULL DEFAULT '{}',
                    risk_flags_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES discovery_batches(batch_id)
                );
                CREATE INDEX IF NOT EXISTS idx_opportunity_candidates_tier_status
                    ON opportunity_candidates(tier, status);
                CREATE INDEX IF NOT EXISTS idx_opportunity_candidates_ticker
                    ON opportunity_candidates(ticker);

                CREATE TABLE IF NOT EXISTS source_signals (
                    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    raw_artifact_id TEXT NOT NULL,
                    source_timestamp TEXT,
                    mentions INTEGER,
                    sentiment TEXT,
                    evidence_json TEXT NOT NULL,
                    raw_text_ref TEXT,
                    UNIQUE(candidate_id, source, raw_artifact_id),
                    FOREIGN KEY(candidate_id) REFERENCES opportunity_candidates(candidate_id)
                );

                CREATE TABLE IF NOT EXISTS handoffs (
                    candidate_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    ata_final_signal TEXT,
                    ata_confidence TEXT,
                    plan_id TEXT,
                    PRIMARY KEY(candidate_id, run_id),
                    FOREIGN KEY(candidate_id) REFERENCES opportunity_candidates(candidate_id)
                );
                CREATE INDEX IF NOT EXISTS idx_handoffs_candidate_status
                    ON handoffs(candidate_id, status);

                CREATE TABLE IF NOT EXISTS outcomes (
                    candidate_id TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    raw_return REAL,
                    benchmark_return REAL,
                    alpha_return REAL,
                    mfe REAL,
                    mae REAL,
                    resolved_at TEXT NOT NULL,
                    PRIMARY KEY(candidate_id, horizon_days),
                    FOREIGN KEY(candidate_id) REFERENCES opportunity_candidates(candidate_id)
                );

                CREATE TABLE IF NOT EXISTS discovery_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    batch_id TEXT,
                    candidate_id TEXT,
                    ticker TEXT,
                    source TEXT,
                    status TEXT NOT NULL,
                    message TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    duration_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_events_batch_time
                    ON discovery_events(batch_id, event_time);
                CREATE INDEX IF NOT EXISTS idx_discovery_events_candidate
                    ON discovery_events(candidate_id, event_time);
                CREATE INDEX IF NOT EXISTS idx_discovery_events_type_status
                    ON discovery_events(event_type, status);

                CREATE TABLE IF NOT EXISTS n8n_ingest_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    event_type TEXT NOT NULL,
                    source_id TEXT,
                    source_name TEXT,
                    source_type TEXT,
                    source_url TEXT,
                    article_title TEXT,
                    article_canonical_url TEXT,
                    article_published_at TEXT,
                    article_author TEXT,
                    article_excerpt TEXT,
                    article_guid TEXT,
                    summary_zh TEXT,
                    companies_or_tickers_json TEXT NOT NULL DEFAULT '[]',
                    watch_items_json TEXT NOT NULL DEFAULT '[]',
                    enriched_json TEXT NOT NULL DEFAULT '{}',
                    raw_event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_n8n_ingest_events_canonical_url
                    ON n8n_ingest_events(article_canonical_url)
                    WHERE article_canonical_url IS NOT NULL AND article_canonical_url != '';
                """
            )
            candidate_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(opportunity_candidates)").fetchall()
            }
            if "discovered_at" not in candidate_columns:
                conn.execute("ALTER TABLE opportunity_candidates ADD COLUMN discovered_at TEXT")
            if "score_components_json" not in candidate_columns:
                conn.execute("ALTER TABLE opportunity_candidates ADD COLUMN score_components_json TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "handoffs", "plan_id", "TEXT")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_n8n_ingest_event(
        self,
        *,
        event: dict[str, Any],
        enriched: dict[str, Any],
        received_at: str,
    ) -> tuple[bool, str]:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            raise ValueError("event_id is required")
        source = event.get("source") or {}
        article = event.get("article") or {}
        analysis = event.get("analysis") or {}
        canonical_url = str(article.get("canonical_url") or "")
        companies_or_tickers = analysis.get("companies_or_tickers") or []
        watch_items = analysis.get("watch_items") or []

        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT event_id FROM n8n_ingest_events
                WHERE event_id = ?
                   OR (? != '' AND article_canonical_url = ?)
                LIMIT 1
                """,
                (event_id, canonical_url, canonical_url),
            ).fetchone()
            deduped = existing is not None
            stored_event_id = str(existing["event_id"]) if existing else event_id
            conn.execute(
                """
                INSERT INTO n8n_ingest_events (
                    event_id, run_id, event_type, source_id, source_name, source_type, source_url,
                    article_title, article_canonical_url, article_published_at, article_author,
                    article_excerpt, article_guid, summary_zh, companies_or_tickers_json,
                    watch_items_json, enriched_json, raw_event_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    event_type=excluded.event_type,
                    source_id=excluded.source_id,
                    source_name=excluded.source_name,
                    source_type=excluded.source_type,
                    source_url=excluded.source_url,
                    article_title=excluded.article_title,
                    article_canonical_url=excluded.article_canonical_url,
                    article_published_at=excluded.article_published_at,
                    article_author=excluded.article_author,
                    article_excerpt=excluded.article_excerpt,
                    article_guid=excluded.article_guid,
                    summary_zh=excluded.summary_zh,
                    companies_or_tickers_json=excluded.companies_or_tickers_json,
                    watch_items_json=excluded.watch_items_json,
                    enriched_json=excluded.enriched_json,
                    raw_event_json=excluded.raw_event_json,
                    updated_at=excluded.updated_at
                """,
                (
                    stored_event_id,
                    event.get("run_id"),
                    event.get("event_type") or "",
                    source.get("id"),
                    source.get("name"),
                    source.get("type"),
                    source.get("url"),
                    article.get("title"),
                    canonical_url,
                    article.get("published_at"),
                    article.get("author"),
                    article.get("excerpt"),
                    article.get("guid"),
                    analysis.get("summary_zh"),
                    _json_dump(companies_or_tickers if isinstance(companies_or_tickers, list) else [companies_or_tickers]),
                    _json_dump(watch_items if isinstance(watch_items, list) else [watch_items]),
                    _json_dump(enriched),
                    _json_dump(event),
                    received_at,
                    received_at,
                ),
            )
            return deduped, stored_event_id

    def upsert_batch(self, batch: DiscoveryBatch) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO discovery_batches (batch_id, source, generated_at, config_json, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    source=excluded.source,
                    generated_at=excluded.generated_at,
                    config_json=excluded.config_json,
                    status=excluded.status
                """,
                (batch.batch_id, batch.source, batch.generated_at, _json_dump(batch.config_json), batch.status),
            )

    def ensure_batch(self, batch: DiscoveryBatch) -> None:
        self.upsert_batch(batch)

    def update_batch_status(self, batch_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE discovery_batches SET status = ? WHERE batch_id = ?",
                (status, batch_id),
            )

    def list_batches(self, *, limit: int | None = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM discovery_batches ORDER BY generated_at DESC"
        params: list[Any] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["config_json"] = _json_load(data.get("config_json"), {})
            result.append(data)
        return result

    def upsert_candidate(self, candidate: OpportunityCandidate, *, updated_at: str) -> None:
        with self._connect() as conn:
            self._upsert_candidate(conn, candidate, updated_at=updated_at)

    def upsert_candidates(self, candidates: Iterable[OpportunityCandidate], *, updated_at: str) -> None:
        with self._connect() as conn:
            for candidate in candidates:
                self._upsert_candidate(conn, candidate, updated_at=updated_at)

    def _upsert_candidate(
        self,
        conn: sqlite3.Connection,
        candidate: OpportunityCandidate,
        *,
        updated_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO opportunity_candidates (
                candidate_id, batch_id, ticker, tier, alpha_score, opportunity_type,
                direction_hint, theme, catalyst, ttl, cooldown_state,
                recommended_analysts_json, run_reason, rejected_reason, status,
                discovered_at, score_components_json, risk_flags_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                batch_id=excluded.batch_id,
                ticker=excluded.ticker,
                tier=excluded.tier,
                alpha_score=excluded.alpha_score,
                opportunity_type=excluded.opportunity_type,
                direction_hint=excluded.direction_hint,
                theme=excluded.theme,
                catalyst=excluded.catalyst,
                ttl=excluded.ttl,
                cooldown_state=excluded.cooldown_state,
                recommended_analysts_json=excluded.recommended_analysts_json,
                run_reason=excluded.run_reason,
                rejected_reason=excluded.rejected_reason,
                status=excluded.status,
                discovered_at=COALESCE(opportunity_candidates.discovered_at, excluded.discovered_at),
                score_components_json=excluded.score_components_json,
                risk_flags_json=excluded.risk_flags_json,
                updated_at=excluded.updated_at
            """,
            (
                candidate.candidate_id,
                candidate.batch_id,
                candidate.ticker,
                candidate.tier,
                candidate.alpha_score,
                candidate.opportunity_type,
                candidate.direction_hint,
                candidate.theme,
                candidate.catalyst,
                candidate.ttl,
                candidate.cooldown_state,
                _json_dump(candidate.recommended_analysts),
                candidate.run_reason,
                candidate.rejected_reason,
                candidate.status,
                candidate.discovered_at or updated_at,
                _json_dump(candidate.score_components),
                _json_dump(candidate.risk_flags),
                updated_at,
            ),
        )
        for signal in candidate.source_signals:
            conn.execute(
                """
                INSERT INTO source_signals (
                    candidate_id, source, raw_artifact_id, source_timestamp,
                    mentions, sentiment, evidence_json, raw_text_ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id, source, raw_artifact_id) DO UPDATE SET
                    source_timestamp=excluded.source_timestamp,
                    mentions=excluded.mentions,
                    sentiment=excluded.sentiment,
                    evidence_json=excluded.evidence_json,
                    raw_text_ref=excluded.raw_text_ref
                """,
                (
                    signal.candidate_id,
                    signal.source,
                    signal.raw_artifact_id,
                    signal.source_timestamp,
                    signal.mentions,
                    signal.sentiment,
                    _json_dump(signal.evidence_json),
                    signal.raw_text_ref,
                ),
            )

    def list_candidates(
        self,
        *,
        tiers: list[str] | None = None,
        status: str | None = "open",
        limit: int | None = None,
        ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if tiers:
            placeholders = ",".join("?" for _ in tiers)
            clauses.append(f"tier IN ({placeholders})")
            params.extend(tiers)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if ticker:
            clauses.append("ticker = ?")
            params.append(str(ticker).strip().upper())
        query = "SELECT * FROM opportunity_candidates"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY alpha_score DESC, updated_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._candidate_row_to_dict(row) for row in rows]

    def get_candidate_by_ticker(self, ticker: str, *, status: str | None = "open") -> dict[str, Any] | None:
        rows = self.list_candidates(tiers=None, status=status, limit=1, ticker=ticker)
        return rows[0] if rows else None

    def mark_older_open_candidates_superseded(self, *, updated_at: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE opportunity_candidates
                SET status='superseded',
                    cooldown_state='superseded',
                    updated_at=?
                WHERE status='open'
                  AND candidate_id NOT IN (
                    SELECT candidate_id
                    FROM (
                        SELECT candidate_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY ticker
                                   ORDER BY updated_at DESC, alpha_score DESC, candidate_id DESC
                               ) AS rn
                        FROM opportunity_candidates
                        WHERE status='open'
                    )
                    WHERE rn=1
                  )
                """,
                (updated_at,),
            )
            return int(cursor.rowcount or 0)

    def update_candidate_status(
        self,
        candidate_id: str,
        *,
        status: str,
        cooldown_state: str | None = None,
        score_components: dict[str, Any] | None = None,
        risk_flags: list[str] | None = None,
        updated_at: str,
    ) -> None:
        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, updated_at]
        if cooldown_state is not None:
            assignments.append("cooldown_state = ?")
            params.append(cooldown_state)
        if score_components is not None:
            assignments.append("score_components_json = ?")
            params.append(_json_dump(score_components))
        if risk_flags is not None:
            assignments.append("risk_flags_json = ?")
            params.append(_json_dump(risk_flags))
        params.append(candidate_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE opportunity_candidates SET {', '.join(assignments)} WHERE candidate_id = ?",
                params,
            )

    def get_source_signals(self, candidate_id: str) -> list[SourceSignal]:
        rows = self.list_source_signals(candidate_ids=[candidate_id])
        return [
            SourceSignal(
                candidate_id=row["candidate_id"],
                source=row["source"],
                raw_artifact_id=row["raw_artifact_id"],
                source_timestamp=row.get("source_timestamp"),
                mentions=row.get("mentions"),
                sentiment=row.get("sentiment"),
                evidence_json=row.get("evidence_json") or {},
                raw_text_ref=row.get("raw_text_ref"),
            )
            for row in rows
        ]

    def list_source_signals(self, *, candidate_ids: list[str] | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            clauses.append(f"candidate_id IN ({placeholders})")
            params.extend(candidate_ids)
        query = "SELECT * FROM source_signals"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY candidate_id, source, signal_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["evidence_json"] = _json_load(data.get("evidence_json"), {})
            result.append(data)
        return result

    def list_research_articles(
        self,
        *,
        limit: int | None = 50,
        source_id: str | None = None,
        article_kind: str | None = None,
        ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("e.source_id = ?")
            params.append(source_id)
        if article_kind:
            clauses.append("json_extract(e.enriched_json, '$.article_kind') = ?")
            params.append(article_kind)
        if ticker:
            normalized_ticker = str(ticker).strip().upper()
            clauses.append(
                """
                (
                    EXISTS (
                        SELECT 1
                        FROM json_each(e.enriched_json, '$.primary_tickers')
                        WHERE UPPER(json_each.value) = ?
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM json_each(e.enriched_json, '$.secondary_tickers')
                        WHERE UPPER(json_each.value) = ?
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM source_signals ss_filter
                        JOIN opportunity_candidates oc_filter
                          ON oc_filter.candidate_id = ss_filter.candidate_id
                        WHERE ss_filter.raw_artifact_id IN (e.event_id, e.article_canonical_url)
                          AND ss_filter.source = 'research_article'
                          AND oc_filter.ticker = ?
                    )
                )
                """
            )
            params.extend([normalized_ticker, normalized_ticker, normalized_ticker])
        query = """
            SELECT
                e.*,
                COUNT(DISTINCT ss.candidate_id) AS linked_candidate_count,
                GROUP_CONCAT(DISTINCT oc.ticker) AS linked_candidate_tickers
            FROM n8n_ingest_events e
            LEFT JOIN source_signals ss
              ON ss.raw_artifact_id IN (e.event_id, e.article_canonical_url)
             AND ss.source = 'research_article'
            LEFT JOIN opportunity_candidates oc
              ON oc.candidate_id = ss.candidate_id
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += """
            GROUP BY e.event_id
            ORDER BY COALESCE(e.article_published_at, e.created_at) DESC, e.updated_at DESC
        """
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._research_article_row_to_dict(row) for row in rows]

    def get_research_article(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM n8n_ingest_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if not row:
            return None
        article = self._research_article_row_to_dict(row)
        with self._connect() as conn:
            signal_rows = conn.execute(
                """
                SELECT
                    ss.*,
                    oc.ticker,
                    oc.tier,
                    oc.alpha_score,
                    oc.opportunity_type,
                    oc.direction_hint,
                    oc.theme,
                    oc.status AS candidate_status,
                    oc.score_components_json
                FROM source_signals ss
                JOIN opportunity_candidates oc ON oc.candidate_id = ss.candidate_id
                WHERE ss.raw_artifact_id IN (?, ?)
                  AND ss.source = 'research_article'
                ORDER BY oc.alpha_score DESC, oc.ticker
                """,
                (event_id, article.get("article_canonical_url")),
            ).fetchall()
        linked_candidates = []
        for signal_row in signal_rows:
            data = dict(signal_row)
            data["evidence_json"] = _json_load(data.get("evidence_json"), {})
            data["score_components"] = _json_load(data.pop("score_components_json"), {})
            linked_candidates.append(data)
        article["linked_candidates"] = linked_candidates
        return article

    def list_outcomes(self, *, status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        query = """
            SELECT
                o.*,
                c.ticker,
                c.tier,
                c.alpha_score,
                c.opportunity_type,
                c.theme,
                c.score_components_json,
                c.risk_flags_json,
                c.status AS candidate_status
            FROM outcomes o
            JOIN opportunity_candidates c ON c.candidate_id=o.candidate_id
        """
        if status:
            query += " WHERE c.status = ?"
            params.append(status)
        query += " ORDER BY o.horizon_days, c.theme, c.ticker"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["score_components"] = _json_load(data.pop("score_components_json"), {})
            data["risk_flags"] = _json_load(data.pop("risk_flags_json"), [])
            result.append(data)
        return result

    def recent_handoffs(self, ticker: str, *, since_iso: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT h.*
                FROM handoffs h
                JOIN opportunity_candidates c ON c.candidate_id=h.candidate_id
                WHERE c.ticker=? AND h.executed_at >= ?
                ORDER BY h.executed_at DESC
                """,
                (ticker, since_iso),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_handoffs_all(self, *, since_iso: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT h.*, c.ticker, c.tier, c.alpha_score
                FROM handoffs h
                JOIN opportunity_candidates c ON c.candidate_id=h.candidate_id
                WHERE h.executed_at >= ?
                ORDER BY h.executed_at DESC
                """,
                (since_iso,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_handoffs(self, *, candidate_ids: list[str] | None = None, limit: int | None = 500) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            clauses.append(f"h.candidate_id IN ({placeholders})")
            params.extend(candidate_ids)
        query = """
            SELECT h.*, c.ticker, c.tier, c.alpha_score
            FROM handoffs h
            JOIN opportunity_candidates c ON c.candidate_id=h.candidate_id
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY h.executed_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_handoff(self, handoff: Handoff) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO handoffs (
                    candidate_id, run_id, status, executed_at, ata_final_signal, ata_confidence, plan_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id, run_id) DO UPDATE SET
                    status=excluded.status,
                    executed_at=excluded.executed_at,
                    ata_final_signal=excluded.ata_final_signal,
                    ata_confidence=excluded.ata_confidence,
                    plan_id=COALESCE(excluded.plan_id, handoffs.plan_id)
                """,
                (
                    handoff.candidate_id,
                    handoff.run_id,
                    handoff.status,
                    handoff.executed_at,
                    handoff.ata_final_signal,
                    handoff.ata_confidence,
                    handoff.plan_id,
                ),
            )

    def upsert_outcome(self, outcome: Outcome) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outcomes (
                    candidate_id, horizon_days, raw_return, benchmark_return,
                    alpha_return, mfe, mae, resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id, horizon_days) DO UPDATE SET
                    raw_return=excluded.raw_return,
                    benchmark_return=excluded.benchmark_return,
                    alpha_return=excluded.alpha_return,
                    mfe=excluded.mfe,
                    mae=excluded.mae,
                    resolved_at=excluded.resolved_at
                """,
                (
                    outcome.candidate_id,
                    outcome.horizon_days,
                    outcome.raw_return,
                    outcome.benchmark_return,
                    outcome.alpha_return,
                    outcome.mfe,
                    outcome.mae,
                    outcome.resolved_at,
                ),
            )

    def insert_event(self, event: DiscoveryEvent) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO discovery_events (
                    event_time, event_type, batch_id, candidate_id, ticker, source,
                    status, message, payload_json, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_time,
                    event.event_type,
                    event.batch_id,
                    event.candidate_id,
                    event.ticker,
                    event.source,
                    event.status,
                    event.message,
                    _json_dump(event.payload_json),
                    event.duration_ms,
                ),
            )
            return int(cursor.lastrowid)

    def list_events(
        self,
        *,
        batch_id: str | None = None,
        candidate_id: str | None = None,
        event_type: str | None = None,
        status: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if batch_id:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if candidate_id:
            clauses.append("candidate_id = ?")
            params.append(candidate_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        query = "SELECT * FROM discovery_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["payload_json"] = _json_load(data.get("payload_json"), {})
            result.append(data)
        return result

    def _candidate_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["recommended_analysts"] = _json_load(data.pop("recommended_analysts_json"), [])
        data["risk_flags"] = _json_load(data.pop("risk_flags_json"), [])
        data["score_components"] = _json_load(data.pop("score_components_json"), {})
        return data

    def _research_article_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["companies_or_tickers"] = _json_load(data.pop("companies_or_tickers_json", None), [])
        data["watch_items"] = _json_load(data.pop("watch_items_json", None), [])
        data["enriched"] = _json_load(data.pop("enriched_json", None), {})
        data["raw_event"] = _json_load(data.pop("raw_event_json", None), {})
        tickers = data.pop("linked_candidate_tickers", None)
        data["linked_candidate_tickers"] = [ticker for ticker in str(tickers or "").split(",") if ticker]
        data["linked_candidate_count"] = int(data.get("linked_candidate_count") or 0)
        return data

    def dump_candidate(self, candidate: OpportunityCandidate) -> dict[str, Any]:
        data = asdict(candidate)
        data["source_signals"] = [asdict(signal) for signal in candidate.source_signals]
        return data

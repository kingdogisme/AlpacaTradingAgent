from __future__ import annotations

from dataclasses import asdict
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Iterable

from tradingagents.default_config import DEFAULT_CONFIG

from .decision_parser import parse_decision_text
from .models import (
    CriticRecordV1,
    DecisionRecordV1,
    EpisodeRecord,
    EvaluationOutcomeRecord,
    EvaluationTargetRecord,
    ExperimentRecordV1,
    LayerEvaluationResultRecord,
    LayerEvaluationTargetRecord,
    MemoryItemRecordV1,
    MemoryPromotionRecordV1,
    MemoryRetrievalRecordV1,
    QualityObservationRecordV1,
    QualityIndexRecordV1,
    QualityReconciliationRecordV1,
    RetrievalPackRecordV1,
    RewardRecordV1,
    RunIndexRecordV1,
    SourceReliabilityRecordV1,
    TraceSpanV1,
)


from .ledger_records import json_dump as _json_dump, json_load as _json_load
from .ledger_schema import SCHEMA_SQL, apply_schema_migrations
from .ledger_trace import (
    MEMORY_ITEM_TYPES,
    TRACE_EVENT_TYPES,
    _event_agent_name,
    _event_metadata,
    _event_node_name,
    _flatten_json_lists,
    _safe_span_token,
    _token_estimate,
)


def default_ledger_path() -> Path:
    return Path(DEFAULT_CONFIG["episode_ledger_path"]).expanduser()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_config_hash(config: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in (config or {}).items()
        if key
        not in {
            "api_key",
            "openai_api_key",
            "alpaca_api_key",
            "alpaca_secret_key",
            "finnhub_api_key",
            "coindesk_api_key",
        }
        and not str(key).lower().endswith(("api_key", "secret_key", "token"))
    }
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def git_provenance() -> dict[str, str | None]:
    """Best-effort local source identity for auditable evaluation buckets."""
    root = Path(__file__).resolve().parents[2]

    def _git(args: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout

    commit = (_git(["rev-parse", "HEAD"]) or "").strip() or None
    diff = _git(["diff", "--binary", "HEAD"])
    dirty_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()[:16] if diff else None
    return {
        "git_commit": commit,
        "dirty_diff_hash": dirty_hash,
        "system_version": f"{commit[:12]}{'-dirty-' + dirty_hash if dirty_hash else ''}" if commit else "unknown",
    }


def trust_tier_for(run_policy: str | None, leakage_risk: str | None) -> str:
    if str(leakage_risk or "").lower() == "high":
        return "legacy_observed"
    policy = str(run_policy or "").lower()
    if policy in {"pit_strict", "historical_strict", "current_pit_rerun"}:
        return "current_pit_rerun"
    if policy == "live_forward":
        return "live_forward"
    return "legacy_observed"


class EpisodeLedger:
    """SQLite-backed episode, decision, and reward index."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else default_ledger_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            apply_schema_migrations(conn)

    def start_episode(
        self,
        run_id: str,
        symbol: str,
        trade_date: str,
        config: dict[str, Any],
        selected_analysts: Iterable[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes (
                    run_id, symbol, trade_date, status, config_json,
                    selected_analysts_json, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    trade_date=excluded.trade_date,
                    status='running',
                    config_json=excluded.config_json,
                    selected_analysts_json=excluded.selected_analysts_json,
                    metadata_json=excluded.metadata_json,
                    error_message=NULL,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    symbol,
                    str(trade_date),
                    _json_dump(config),
                    _json_dump(list(selected_analysts)),
                    _json_dump(metadata or {}),
                    now,
                    now,
                ),
            )
        self.upsert_experiment(run_id, config, selected_analysts=list(selected_analysts), metadata=metadata or {})

    def complete_episode(
        self,
        run_id: str,
        final_state: dict[str, Any],
        final_signal: str,
        audit_path: str | None,
    ) -> None:
        trading_mode = final_state.get("trading_mode") or (
            "trading" if final_signal in {"LONG", "NEUTRAL", "SHORT"} else "investment"
        )
        horizon = final_state.get("trading_horizon")
        decisions = self._decisions_from_state(
            run_id,
            final_state,
            final_signal,
            trading_mode=trading_mode,
            horizon=horizon,
        )
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET status='completed',
                    final_signal=?,
                    audit_path=?,
                    error_message=NULL,
                    updated_at=?
                WHERE run_id=?
                """,
                (final_signal, audit_path, now, run_id),
            )
            for decision in decisions:
                self._upsert_decision(conn, decision)
        self.normalize_trace(run_id)

    def fail_episode(self, run_id: str, error_message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET status='failed', error_message=?, updated_at=?
                WHERE run_id=?
                """,
                (error_message, _utc_now_iso(), run_id),
            )

    def upsert_reward_status(
        self,
        run_id: str,
        reward_version: str,
        reward_status: str,
        *,
        holding_days: int = 0,
        components: dict[str, Any] | None = None,
        data_source: str = "RewardResolver",
        resolved_at: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rewards (
                    run_id, reward_version, reward_status, holding_days, raw_return,
                    benchmark_return, alpha_return, oracle_label, classification_reward,
                    pnl_reward, reward_scalar, components_json, resolved_at, data_source
                )
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)
                ON CONFLICT(run_id, reward_version) DO UPDATE SET
                    reward_status=excluded.reward_status,
                    holding_days=excluded.holding_days,
                    raw_return=NULL,
                    benchmark_return=NULL,
                    alpha_return=NULL,
                    oracle_label=NULL,
                    classification_reward=NULL,
                    pnl_reward=NULL,
                    reward_scalar=NULL,
                    components_json=excluded.components_json,
                    resolved_at=excluded.resolved_at,
                    data_source=excluded.data_source
                """,
                (
                    run_id,
                    reward_version,
                    reward_status,
                    holding_days,
                    _json_dump(components or {}),
                    resolved_at or _utc_now_iso(),
                    data_source,
                ),
            )

    def list_episodes(self, filters: dict[str, Any] | None = None) -> list[EpisodeRecord]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("status", "symbol"):
            if filters.get(key):
                clauses.append(f"e.{key} = ?")
                params.append(filters[key])
        if filters.get("since"):
            clauses.append("e.trade_date >= ?")
            params.append(filters["since"])
        if filters.get("until"):
            clauses.append("e.trade_date <= ?")
            params.append(filters["until"])
        if filters.get("reward_status"):
            clauses.append("r.reward_status = ?")
            params.append(filters["reward_status"])
        query = """
            SELECT e.*
            FROM episodes e
            LEFT JOIN rewards r ON r.run_id=e.run_id
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY e.trade_date DESC, e.created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._episode_from_row(row) for row in rows]

    def load_episode(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            episode = conn.execute("SELECT * FROM episodes WHERE run_id=?", (run_id,)).fetchone()
            if episode is None:
                return None
            decisions = conn.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY created_at, stage",
                (run_id,),
            ).fetchall()
            rewards = conn.execute(
                "SELECT * FROM rewards WHERE run_id=? ORDER BY resolved_at",
                (run_id,),
            ).fetchall()
            traces = conn.execute(
                "SELECT * FROM trace_spans WHERE run_id=? ORDER BY started_at, span_id",
                (run_id,),
            ).fetchall()
            critics = conn.execute(
                "SELECT * FROM critic_records WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
            experiment = conn.execute(
                "SELECT * FROM experiments WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return {
            **asdict(self._episode_from_row(episode)),
            "decisions": [self._decision_from_row(row) for row in decisions],
            "rewards": [self._reward_from_row(row) for row in rewards],
            "trace_spans": [self._trace_span_from_row(row) for row in traces],
            "critic_records": [self._critic_from_row(row) for row in critics],
            "experiment": self._experiment_from_row(experiment) if experiment else None,
        }

    def load_trajectory(self, run_id: str) -> list[dict[str, Any]]:
        episode = self.load_episode(run_id)
        if not episode or not episode.get("audit_path"):
            return []
        path = Path(str(episode["audit_path"]))
        if not path.exists():
            return []
        try:
            audit = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

        trajectory: list[dict[str, Any]] = []
        for event in audit.get("events", []):
            event_type = event.get("type")
            if event_type not in TRACE_EVENT_TYPES:
                continue
            trajectory.append(
                {
                    "timestamp": event.get("timestamp"),
                    "type": event_type,
                    "payload": event.get("payload", {}),
                }
            )
        return trajectory

    def get_pending_reward_episodes(self, as_of: str | None = None) -> list[dict[str, Any]]:
        _ = as_of
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, d.action, d.trading_mode, d.horizon
                FROM episodes e
                LEFT JOIN decisions d
                    ON d.run_id=e.run_id AND d.stage='final'
                LEFT JOIN rewards r
                    ON r.run_id=e.run_id
                WHERE e.status='completed' AND r.run_id IS NULL
                ORDER BY e.trade_date ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_reward(self, reward: RewardRecordV1) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rewards (
                    run_id, reward_version, reward_status, holding_days, raw_return, benchmark_return,
                    alpha_return, oracle_label, classification_reward, pnl_reward,
                    reward_scalar, components_json, resolved_at, data_source
                )
                VALUES (?, ?, 'resolved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, reward_version) DO UPDATE SET
                    reward_status='resolved',
                    holding_days=excluded.holding_days,
                    raw_return=excluded.raw_return,
                    benchmark_return=excluded.benchmark_return,
                    alpha_return=excluded.alpha_return,
                    oracle_label=excluded.oracle_label,
                    classification_reward=excluded.classification_reward,
                    pnl_reward=excluded.pnl_reward,
                    reward_scalar=excluded.reward_scalar,
                    components_json=excluded.components_json,
                    resolved_at=excluded.resolved_at,
                    data_source=excluded.data_source
                """,
                (
                    reward.run_id,
                    reward.reward_version,
                    reward.holding_days,
                    reward.raw_return,
                    reward.benchmark_return,
                    reward.alpha_return,
                    reward.oracle_label,
                    reward.classification_reward,
                    reward.pnl_reward,
                    reward.reward_scalar,
                    _json_dump(reward.components_json),
                    reward.resolved_at,
                    reward.data_source,
                ),
            )

    def upsert_evaluation_target(self, target: EvaluationTargetRecord) -> None:
        from .targets import EvaluationTargetRepository

        EvaluationTargetRepository(self).upsert_target(target)

    def list_evaluation_targets(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from .targets import EvaluationTargetRepository

        return EvaluationTargetRepository(self).list_targets(filters)

    def upsert_evaluation_outcome(self, outcome: EvaluationOutcomeRecord) -> None:
        from .targets import EvaluationTargetRepository

        EvaluationTargetRepository(self).upsert_outcome(outcome)

    def list_evaluation_outcomes(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from .targets import EvaluationTargetRepository

        return EvaluationTargetRepository(self).list_outcomes(filters)

    def upsert_layer_evaluation_target(self, target: LayerEvaluationTargetRecord | Any) -> None:
        from .layered import LayerEvaluationRepository

        LayerEvaluationRepository(self).upsert_target(target)

    def get_layer_evaluation_target(self, target_id: str) -> dict[str, Any] | None:
        from .layered import LayerEvaluationRepository

        return LayerEvaluationRepository(self).get_target(target_id)

    def list_layer_evaluation_targets(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from .layered import LayerEvaluationRepository

        return LayerEvaluationRepository(self).list_targets(filters)

    def upsert_layer_evaluation_record(self, record: LayerEvaluationResultRecord | Any) -> None:
        from .layered import LayerEvaluationRepository

        LayerEvaluationRepository(self).upsert_record(record)

    def list_layer_evaluation_records(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from .layered import LayerEvaluationRepository

        return LayerEvaluationRepository(self).list_records(filters)

    def report_rows(
        self,
        *,
        since: str | None = None,
        include_high_leakage: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["e.status='completed'"]
        params: list[Any] = []
        if since:
            clauses.append("e.trade_date >= ?")
            params.append(since)
        if not include_high_leakage:
            clauses.append("json_extract(e.metadata_json, '$.data_leakage_risk') IS NOT 'high'")
        query = f"""
            SELECT
                e.run_id, e.symbol, e.trade_date, e.status, e.config_json,
                e.metadata_json, e.final_signal, e.error_message,
                d.action, d.trading_mode, d.horizon, d.confidence,
                r.reward_version, r.reward_status, r.raw_return, r.benchmark_return, r.alpha_return,
                r.oracle_label, r.classification_reward, r.pnl_reward, r.reward_scalar,
                r.components_json AS reward_components_json
                , x.experiment_id, x.config_hash, x.prompt_version, x.model_provider,
                x.quick_model, x.deep_model, x.memory_policy, x.critic_version,
                x.leakage_risk
                , COALESCE(ts.trace_span_count, 0) AS trace_span_count
                , COALESCE(cr.critic_count, 0) AS critic_count
                , cr.failure_tags_json AS critic_failure_tags_json
                , COALESCE(mi.memory_candidate_count, 0) AS memory_candidate_count
            FROM episodes e
            LEFT JOIN decisions d ON d.run_id=e.run_id AND d.stage='final'
            LEFT JOIN rewards r ON r.run_id=e.run_id
            LEFT JOIN experiments x ON x.run_id=e.run_id
            LEFT JOIN (
                SELECT run_id, COUNT(*) AS trace_span_count
                FROM trace_spans
                GROUP BY run_id
            ) ts ON ts.run_id=e.run_id
            LEFT JOIN (
                SELECT run_id, COUNT(*) AS critic_count,
                       '[' || GROUP_CONCAT(failure_tags_json) || ']' AS failure_tags_json
                FROM critic_records
                GROUP BY run_id
            ) cr ON cr.run_id=e.run_id
            LEFT JOIN (
                SELECT json_extract(evidence_json, '$.run_id') AS run_id,
                       COUNT(*) AS memory_candidate_count
                FROM memory_items
                WHERE status='candidate'
                GROUP BY json_extract(evidence_json, '$.run_id')
            ) mi ON mi.run_id=e.run_id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.trade_date ASC, e.symbol ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["config"] = _json_load(item.pop("config_json", None), {})
            item["metadata"] = _json_load(item.pop("metadata_json", None), {})
            item["critic_failure_tags"] = _flatten_json_lists(
                _json_load(item.pop("critic_failure_tags_json", None), [])
            )
            item["reward_components"] = _json_load(item.pop("reward_components_json", None), {})
            result.append(item)
        return result

    def normalize_trace(self, run_id: str) -> list[TraceSpanV1]:
        episode = self.load_episode(run_id)
        if not episode or not episode.get("audit_path"):
            return []
        path = Path(str(episode["audit_path"]))
        if not path.exists():
            return []
        try:
            audit = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

        spans: list[TraceSpanV1] = []
        event_counts: dict[str, int] = {}
        latest_node_span_id: str | None = None
        artifact_ref = str(path)

        for event in audit.get("events", []):
            event_type = event.get("type")
            if event_type not in TRACE_EVENT_TYPES:
                continue
            payload = event.get("payload", {}) or {}
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
            timestamp = event.get("timestamp")
            node_name = _event_node_name(payload)
            agent_name = _event_agent_name(event_type, payload)
            tool_name = payload.get("tool_name") if event_type == "tool_call" else None
            span_type = "node_event" if event_type == "node_execution" else event_type
            span_id = f"{_safe_span_token(span_type)}-{event_counts[event_type]:04d}"
            parent_span_id = latest_node_span_id if event_type not in {"node_execution", "node_error"} else None
            status = str(payload.get("status") or ("error" if event_type == "node_error" else "success"))
            started_at = timestamp
            ended_at = timestamp
            duration = payload.get("execution_time_seconds", payload.get("elapsed_seconds"))
            metadata = _event_metadata(event_type, payload)
            if duration is not None:
                metadata["duration_seconds"] = duration
            span = TraceSpanV1(
                run_id=run_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                span_type=span_type,
                agent_name=agent_name,
                node_name=str(node_name) if node_name else None,
                tool_name=str(tool_name) if tool_name else None,
                started_at=started_at,
                ended_at=ended_at,
                status=status,
                metadata_json=metadata,
                artifact_ref=artifact_ref,
            )
            spans.append(span)
            if event_type == "node_execution":
                latest_node_span_id = span_id

        final_state = (audit.get("snapshots") or {}).get("final_state") or {}
        final_decision = final_state.get("final_trade_decision")
        if final_decision:
            event_counts["final_decision"] = event_counts.get("final_decision", 0) + 1
            final_signal = (audit.get("summary") or {}).get("final_signal")
            spans.append(
                TraceSpanV1(
                    run_id=run_id,
                    span_id="final_decision-0001",
                    parent_span_id=latest_node_span_id,
                    span_type="final_decision",
                    agent_name="Risk Manager",
                    node_name=None,
                    tool_name=None,
                    started_at=audit.get("ended_at"),
                    ended_at=audit.get("ended_at"),
                    status=audit.get("status") or "completed",
                    metadata_json={
                        "final_signal": final_signal,
                        "decision_chars": len(str(final_decision)),
                    },
                    artifact_ref=artifact_ref,
                )
            )

        with self._connect() as conn:
            for span in spans:
                self._upsert_trace_span(conn, span)
        return spans

    def list_trace_spans(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trace_spans
                WHERE run_id=?
                ORDER BY started_at, span_id
                """,
                (run_id,),
            ).fetchall()
        return [self._trace_span_from_row(row) for row in rows]

    def upsert_experiment(
        self,
        run_id: str,
        config: dict[str, Any],
        *,
        selected_analysts: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExperimentRecordV1:
        metadata = metadata or {}
        selected_analysts = selected_analysts or list(config.get("selected_analysts") or [])
        config_hash = stable_config_hash(config)
        source = git_provenance()
        leakage_risk = (
            metadata.get("data_leakage_risk")
            or metadata.get("leakage_risk")
            or (config.get("episode_ledger_metadata") or {}).get("data_leakage_risk")
            or config.get("leakage_risk")
            or ("high" if config.get("online_tools", True) else "low")
        )
        run_policy = (
            metadata.get("run_policy")
            or config.get("run_policy")
            or ("pit_strict" if config.get("historical_mode") == "strict" else None)
            or ("live_forward" if config.get("online_tools", True) else "legacy_observed")
        )
        record = ExperimentRecordV1(
            run_id=run_id,
            experiment_id=f"cfg-{config_hash}",
            config_hash=config_hash,
            prompt_version=str(config.get("prompt_version") or "default"),
            model_provider=str(config.get("llm_provider") or "openai"),
            quick_model=str(config.get("quick_think_llm") or "unknown"),
            deep_model=str(config.get("deep_think_llm") or "unknown"),
            selected_analysts=list(selected_analysts),
            memory_policy=str(config.get("memory_policy") or "legacy"),
            critic_version=config.get("critic_version"),
            reward_version=str(config.get("eval_reward_version") or "v1_directional_alpha"),
            leakage_risk=str(leakage_risk),
            system_version=str(metadata.get("system_version") or config.get("system_version") or source["system_version"]),
            git_commit=metadata.get("git_commit") or config.get("git_commit") or source["git_commit"],
            dirty_diff_hash=metadata.get("dirty_diff_hash") or config.get("dirty_diff_hash") or source["dirty_diff_hash"],
            run_policy=str(run_policy),
            data_snapshot_id=metadata.get("data_snapshot_id") or config.get("data_snapshot_id"),
            run_started_at=metadata.get("run_started_at"),
            metadata_json={**metadata, "trust_tier": trust_tier_for(str(run_policy), str(leakage_risk))},
        )
        now = _utc_now_iso()
        run_started_at = record.run_started_at or now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments (
                    run_id, experiment_id, config_hash, prompt_version, model_provider,
                    quick_model, deep_model, selected_analysts_json, memory_policy,
                    critic_version, reward_version, leakage_risk, system_version,
                    git_commit, dirty_diff_hash, run_policy, data_snapshot_id,
                    run_started_at, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    experiment_id=excluded.experiment_id,
                    config_hash=excluded.config_hash,
                    prompt_version=excluded.prompt_version,
                    model_provider=excluded.model_provider,
                    quick_model=excluded.quick_model,
                    deep_model=excluded.deep_model,
                    selected_analysts_json=excluded.selected_analysts_json,
                    memory_policy=excluded.memory_policy,
                    critic_version=excluded.critic_version,
                    reward_version=excluded.reward_version,
                    leakage_risk=excluded.leakage_risk,
                    system_version=excluded.system_version,
                    git_commit=excluded.git_commit,
                    dirty_diff_hash=excluded.dirty_diff_hash,
                    run_policy=excluded.run_policy,
                    data_snapshot_id=excluded.data_snapshot_id,
                    run_started_at=excluded.run_started_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.run_id,
                    record.experiment_id,
                    record.config_hash,
                    record.prompt_version,
                    record.model_provider,
                    record.quick_model,
                    record.deep_model,
                    _json_dump(record.selected_analysts),
                    record.memory_policy,
                    record.critic_version,
                    record.reward_version,
                    record.leakage_risk,
                    record.system_version,
                    record.git_commit,
                    record.dirty_diff_hash,
                    record.run_policy,
                    record.data_snapshot_id,
                    run_started_at,
                    _json_dump(record.metadata_json),
                    now,
                    now,
                ),
            )
        return record

    def add_memory_item(self, record: MemoryItemRecordV1) -> None:
        if record.memory_type not in MEMORY_ITEM_TYPES:
            raise ValueError(f"Unsupported memory_type: {record.memory_type}")
        now = record.created_at or _utc_now_iso()
        state = record.state or record.status or "candidate"
        evidence = record.evidence_json or {}
        metadata = record.metadata_json or {}
        symbol = record.symbol or evidence.get("symbol") or metadata.get("symbol")
        horizon = record.horizon or evidence.get("horizon") or metadata.get("horizon")
        created_by = record.created_by or record.source
        source_run_id = record.source_run_id or evidence.get("run_id")
        source_ref = record.source_ref or evidence.get("source_ref") or (
            f"episode:{source_run_id}" if source_run_id else None
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    memory_item_id, memory_type, content, source, status,
                    symbol, horizon, state, created_by, promotion_score,
                    last_evaluated_at, source_run_id, source_ref,
                    evidence_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_item_id) DO UPDATE SET
                    memory_type=excluded.memory_type,
                    content=excluded.content,
                    source=excluded.source,
                    status=excluded.status,
                    symbol=excluded.symbol,
                    horizon=excluded.horizon,
                    state=excluded.state,
                    created_by=excluded.created_by,
                    promotion_score=excluded.promotion_score,
                    last_evaluated_at=excluded.last_evaluated_at,
                    source_run_id=excluded.source_run_id,
                    source_ref=excluded.source_ref,
                    evidence_json=excluded.evidence_json,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.memory_item_id,
                    record.memory_type,
                    record.content,
                    record.source,
                    state,
                    symbol,
                    horizon,
                    state,
                    created_by,
                    record.promotion_score,
                    record.last_evaluated_at,
                    source_run_id,
                    source_ref,
                    _json_dump(evidence),
                    _json_dump(metadata),
                    now,
                ),
            )
            self._add_memory_links_from_evidence(conn, record.memory_item_id, evidence)

    def record_memory_retrieval(
        self,
        run_id: str,
        memory_item_id: str,
        stage: str,
        rank: int,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record = MemoryRetrievalRecordV1(
            run_id=run_id,
            memory_item_id=memory_item_id,
            stage=stage,
            rank=rank,
            score=score,
            metadata_json=metadata or {},
            created_at=_utc_now_iso(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_retrievals (
                    run_id, memory_item_id, stage, rank, score, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, memory_item_id, stage) DO UPDATE SET
                    rank=excluded.rank,
                    score=excluded.score,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.run_id,
                    record.memory_item_id,
                    record.stage,
                    record.rank,
                    record.score,
                    _json_dump(record.metadata_json),
                    record.created_at,
                ),
            )

    def add_memory_promotion(self, record: MemoryPromotionRecordV1) -> None:
        now = record.created_at or _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_promotions (
                    memory_item_id, from_status, to_status, reason, promoted_by,
                    evidence_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_item_id,
                    record.from_status,
                    record.to_status,
                    record.reason,
                    record.promoted_by,
                    _json_dump(record.evidence_json),
                    now,
                ),
            )
            conn.execute(
                "UPDATE memory_items SET status=? WHERE memory_item_id=?",
                (record.to_status, record.memory_item_id),
            )
            conn.execute(
                "UPDATE memory_items SET state=?, last_evaluated_at=? WHERE memory_item_id=?",
                (record.to_status, now, record.memory_item_id),
            )

    def list_memory_items(
        self,
        *,
        run_id: str | None = None,
        symbol: str | None = None,
        horizon: str | None = None,
        state: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("(source_run_id = ? OR json_extract(evidence_json, '$.run_id') = ?)")
            params.append(run_id)
            params.append(run_id)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if horizon:
            clauses.append("horizon = ?")
            params.append(horizon)
        if state:
            clauses.append("(state = ? OR status = ?)")
            params.extend([state, state])
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        query = "SELECT * FROM memory_items"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._memory_item_from_row(row) for row in rows]

    def load_memory_item(self, memory_item_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE memory_item_id=?",
                (memory_item_id,),
            ).fetchone()
        return self._memory_item_from_row(row) if row else None

    def add_critic_record(self, record: CriticRecordV1) -> None:
        now = record.created_at or _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO critic_records (
                    run_id, critic_version, failure_tags_json, evidence_spans_json,
                    reward_snapshot_json, reflection_text, improvement_candidates_json,
                    parser_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, critic_version) DO UPDATE SET
                    failure_tags_json=excluded.failure_tags_json,
                    evidence_spans_json=excluded.evidence_spans_json,
                    reward_snapshot_json=excluded.reward_snapshot_json,
                    reflection_text=excluded.reflection_text,
                    improvement_candidates_json=excluded.improvement_candidates_json,
                    parser_status=excluded.parser_status,
                    created_at=excluded.created_at
                """,
                (
                    record.run_id,
                    record.critic_version,
                    _json_dump(record.failure_tags),
                    _json_dump(record.evidence_spans),
                    _json_dump(record.reward_snapshot),
                    record.reflection_text,
                    _json_dump(record.improvement_candidates),
                    record.parser_status,
                    now,
                ),
            )

    def list_critic_records(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM critic_records"
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id=?"
            params.append(run_id)
        query += " ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._critic_from_row(row) for row in rows]

    def upsert_quality_index(self, records: list[QualityIndexRecordV1]) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            for record in records:
                conn.execute(
                    """
                    INSERT INTO quality_index (
                        run_id, artifact_ref, tool_name, agent_type, source_id,
                        provider, dataset_type, status, freshness, accuracy,
                        completeness, criticality, flags_json, observed_at,
                        source_age_days, fallback_from, timestamp,
                        requested_trade_date, source_timestamp, max_allowed_timestamp,
                        leakage_status, inputs_json, output_preview, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, artifact_ref) DO UPDATE SET
                        tool_name=excluded.tool_name,
                        agent_type=excluded.agent_type,
                        source_id=excluded.source_id,
                        provider=excluded.provider,
                        dataset_type=excluded.dataset_type,
                        status=excluded.status,
                        freshness=excluded.freshness,
                        accuracy=excluded.accuracy,
                        completeness=excluded.completeness,
                        criticality=excluded.criticality,
                        flags_json=excluded.flags_json,
                        observed_at=excluded.observed_at,
                        source_age_days=excluded.source_age_days,
                        fallback_from=excluded.fallback_from,
                        timestamp=excluded.timestamp,
                        requested_trade_date=excluded.requested_trade_date,
                        source_timestamp=excluded.source_timestamp,
                        max_allowed_timestamp=excluded.max_allowed_timestamp,
                        leakage_status=excluded.leakage_status,
                        inputs_json=excluded.inputs_json,
                        output_preview=excluded.output_preview,
                        updated_at=excluded.updated_at
                    """,
                    (
                        record.run_id,
                        record.artifact_ref,
                        record.tool_name,
                        record.agent_type,
                        record.source_id,
                        record.provider,
                        record.dataset_type,
                        record.status,
                        record.freshness,
                        record.accuracy,
                        record.completeness,
                        record.criticality,
                        _json_dump(record.flags),
                        record.observed_at,
                        record.source_age_days,
                        record.fallback_from,
                        record.timestamp,
                        record.requested_trade_date,
                        record.source_timestamp,
                        record.max_allowed_timestamp,
                        record.leakage_status,
                        _json_dump(record.inputs),
                        record.output_preview,
                        now,
                        now,
                    ),
                )

    def clear_quality_index(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quality_index WHERE run_id=?", (run_id,))

    def list_quality_index(
        self,
        run_id: str,
        *,
        statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["run_id=?"]
        params: list[Any] = [run_id]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        query = f"""
            SELECT * FROM quality_index
            WHERE {' AND '.join(clauses)}
            ORDER BY timestamp, artifact_ref
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._quality_index_from_row(row) for row in rows]

    def upsert_run_index(self, record: RunIndexRecordV1) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_index (
                    index_id, run_id, symbol, trade_date, horizon, status,
                    final_action, confidence, advisory_rating, final_signal,
                    prompt_version, config_hash, model_provider, quick_model,
                    deep_model, selected_analysts_json, quality_status,
                    quality_pass, quality_warn, quality_fail, quality_unknown,
                    critical_failures_json, stale_sources_json,
                    fallback_sources_json, flags_json, audit_ref, audit_path,
                    decision_ref, quality_index_ref, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    index_id=excluded.index_id,
                    symbol=excluded.symbol,
                    trade_date=excluded.trade_date,
                    horizon=excluded.horizon,
                    status=excluded.status,
                    final_action=excluded.final_action,
                    confidence=excluded.confidence,
                    advisory_rating=excluded.advisory_rating,
                    final_signal=excluded.final_signal,
                    prompt_version=excluded.prompt_version,
                    config_hash=excluded.config_hash,
                    model_provider=excluded.model_provider,
                    quick_model=excluded.quick_model,
                    deep_model=excluded.deep_model,
                    selected_analysts_json=excluded.selected_analysts_json,
                    quality_status=excluded.quality_status,
                    quality_pass=excluded.quality_pass,
                    quality_warn=excluded.quality_warn,
                    quality_fail=excluded.quality_fail,
                    quality_unknown=excluded.quality_unknown,
                    critical_failures_json=excluded.critical_failures_json,
                    stale_sources_json=excluded.stale_sources_json,
                    fallback_sources_json=excluded.fallback_sources_json,
                    flags_json=excluded.flags_json,
                    audit_ref=excluded.audit_ref,
                    audit_path=excluded.audit_path,
                    decision_ref=excluded.decision_ref,
                    quality_index_ref=excluded.quality_index_ref,
                    updated_at=excluded.updated_at
                """,
                (
                    record.index_id,
                    record.run_id,
                    record.symbol,
                    record.trade_date,
                    record.horizon,
                    record.status,
                    record.final_action,
                    record.confidence,
                    record.advisory_rating,
                    record.final_signal,
                    record.prompt_version,
                    record.config_hash,
                    record.model_provider,
                    record.quick_model,
                    record.deep_model,
                    _json_dump(record.selected_analysts),
                    record.quality_status,
                    record.quality_pass,
                    record.quality_warn,
                    record.quality_fail,
                    record.quality_unknown,
                    _json_dump(record.critical_failures),
                    _json_dump(record.stale_sources),
                    _json_dump(record.fallback_sources),
                    _json_dump(record.flags),
                    record.audit_ref,
                    record.audit_path,
                    record.decision_ref,
                    record.quality_index_ref,
                    now,
                    now,
                ),
            )

    def list_run_index(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for key in (
            "run_id",
            "symbol",
            "status",
            "horizon",
            "prompt_version",
            "config_hash",
            "final_action",
            "final_signal",
        ):
            if filters.get(key):
                clauses.append(f"{key} = ?")
                params.append(filters[key])
        if filters.get("experiment_id"):
            clauses.append(
                "run_id IN (SELECT run_id FROM experiments WHERE experiment_id = ?)"
            )
            params.append(filters["experiment_id"])
        if filters.get("since"):
            clauses.append("trade_date >= ?")
            params.append(filters["since"])
        if filters.get("until"):
            clauses.append("trade_date <= ?")
            params.append(filters["until"])
        if not filters.get("include_high_leakage"):
            clauses.append(
                "run_id NOT IN (SELECT run_id FROM experiments WHERE leakage_risk = 'high')"
            )
        query = "SELECT * FROM run_index"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY trade_date DESC, updated_at DESC"
        if filters.get("limit"):
            query += " LIMIT ?"
            params.append(int(filters["limit"]))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._run_index_from_row(row) for row in rows]

    def upsert_retrieval_pack(self, record: RetrievalPackRecordV1) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_packs (
                    pack_id, pack_type, policy_version, run_id, symbol, horizon,
                    token_budget, source_refs_json, summary_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pack_id) DO UPDATE SET
                    pack_type=excluded.pack_type,
                    policy_version=excluded.policy_version,
                    run_id=excluded.run_id,
                    symbol=excluded.symbol,
                    horizon=excluded.horizon,
                    token_budget=excluded.token_budget,
                    source_refs_json=excluded.source_refs_json,
                    summary_json=excluded.summary_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.pack_id,
                    record.pack_type,
                    record.policy_version,
                    record.run_id,
                    record.symbol,
                    record.horizon,
                    record.token_budget,
                    _json_dump(record.source_refs),
                    _json_dump(record.summary),
                    now,
                    now,
                ),
            )
            conn.execute("DELETE FROM retrieval_pack_items WHERE pack_id=?", (record.pack_id,))
            for item in record.items:
                conn.execute(
                    """
                    INSERT INTO retrieval_pack_items (
                        pack_id, item_id, item_type, rank, reason, source_ref,
                        token_estimate, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.pack_id,
                        str(item.get("item_id")),
                        str(item.get("item_type") or item.get("kind") or "unknown"),
                        int(item.get("rank") or 0),
                        str(item.get("reason") or ""),
                        str(item.get("source_ref") or ""),
                        int(item.get("token_estimate") or _token_estimate(item.get("payload"))),
                        _json_dump(item.get("payload") or {}),
                        now,
                    ),
                )

    def load_retrieval_pack(self, pack_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            pack = conn.execute(
                "SELECT * FROM retrieval_packs WHERE pack_id=?",
                (pack_id,),
            ).fetchone()
            if pack is None:
                return None
            items = conn.execute(
                """
                SELECT * FROM retrieval_pack_items
                WHERE pack_id=?
                ORDER BY rank, item_id
                """,
                (pack_id,),
            ).fetchall()
        payload = self._retrieval_pack_from_row(pack)
        payload["items"] = [self._retrieval_pack_item_from_row(row) for row in items]
        return payload

    def clear_quality_observations(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quality_observations WHERE run_id=?", (run_id,))

    def upsert_quality_observations(self, records: list[QualityObservationRecordV1]) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            for record in records:
                conn.execute(
                    """
                    INSERT INTO quality_observations (
                        run_id, artifact_ref, symbol, source_id, dataset_type,
                        observation_type, observed_at, value_num, unit,
                        extraction_status, flags_json, source_ref, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, artifact_ref, observation_type) DO UPDATE SET
                        symbol=excluded.symbol,
                        source_id=excluded.source_id,
                        dataset_type=excluded.dataset_type,
                        observed_at=excluded.observed_at,
                        value_num=excluded.value_num,
                        unit=excluded.unit,
                        extraction_status=excluded.extraction_status,
                        flags_json=excluded.flags_json,
                        source_ref=excluded.source_ref,
                        updated_at=excluded.updated_at
                    """,
                    (
                        record.run_id,
                        record.artifact_ref,
                        record.symbol,
                        record.source_id,
                        record.dataset_type,
                        record.observation_type,
                        record.observed_at,
                        record.value_num,
                        record.unit,
                        record.extraction_status,
                        _json_dump(record.flags),
                        record.source_ref,
                        now,
                        now,
                    ),
                )

    def list_quality_observations(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM quality_observations
                WHERE run_id=?
                ORDER BY artifact_ref, observation_type
                """,
                (run_id,),
            ).fetchall()
        return [self._quality_observation_from_row(row) for row in rows]

    def clear_quality_reconciliation(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quality_reconciliation WHERE run_id=?", (run_id,))

    def upsert_quality_reconciliation(
        self,
        records: list[QualityReconciliationRecordV1],
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            for record in records:
                conn.execute(
                    """
                    INSERT INTO quality_reconciliation (
                        reconciliation_id, run_id, symbol, dataset_type, check_type,
                        primary_source, comparison_source, status, severity,
                        delta_pct, flags_json, source_refs_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(reconciliation_id) DO UPDATE SET
                        symbol=excluded.symbol,
                        dataset_type=excluded.dataset_type,
                        check_type=excluded.check_type,
                        primary_source=excluded.primary_source,
                        comparison_source=excluded.comparison_source,
                        status=excluded.status,
                        severity=excluded.severity,
                        delta_pct=excluded.delta_pct,
                        flags_json=excluded.flags_json,
                        source_refs_json=excluded.source_refs_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        record.reconciliation_id,
                        record.run_id,
                        record.symbol,
                        record.dataset_type,
                        record.check_type,
                        record.primary_source,
                        record.comparison_source,
                        record.status,
                        record.severity,
                        record.delta_pct,
                        _json_dump(record.flags),
                        _json_dump(record.source_refs),
                        now,
                        now,
                    ),
                )

    def list_quality_reconciliation(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM quality_reconciliation
                WHERE run_id=?
                ORDER BY check_type, reconciliation_id
                """,
                (run_id,),
            ).fetchall()
        return [self._quality_reconciliation_from_row(row) for row in rows]

    def upsert_source_reliability(self, records: list[SourceReliabilityRecordV1]) -> None:
        with self._connect() as conn:
            for record in records:
                conn.execute(
                    """
                    INSERT INTO source_reliability (
                        source_id, dataset_type, window_days, quality_pass,
                        quality_warn, quality_fail, quality_unknown,
                        fallback_count, stale_count, critical_fail_count,
                        pass_rate, fallback_rate, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, dataset_type, window_days) DO UPDATE SET
                        quality_pass=excluded.quality_pass,
                        quality_warn=excluded.quality_warn,
                        quality_fail=excluded.quality_fail,
                        quality_unknown=excluded.quality_unknown,
                        fallback_count=excluded.fallback_count,
                        stale_count=excluded.stale_count,
                        critical_fail_count=excluded.critical_fail_count,
                        pass_rate=excluded.pass_rate,
                        fallback_rate=excluded.fallback_rate,
                        updated_at=excluded.updated_at
                    """,
                    (
                        record.source_id,
                        record.dataset_type,
                        record.window_days,
                        record.quality_pass,
                        record.quality_warn,
                        record.quality_fail,
                        record.quality_unknown,
                        record.fallback_count,
                        record.stale_count,
                        record.critical_fail_count,
                        record.pass_rate,
                        record.fallback_rate,
                        record.updated_at or _utc_now_iso(),
                    ),
                )

    def list_source_reliability(
        self,
        *,
        window_days: int | None = None,
        source_id: str | None = None,
        dataset_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if window_days:
            clauses.append("window_days=?")
            params.append(window_days)
        if source_id:
            clauses.append("source_id=?")
            params.append(source_id)
        if dataset_type:
            clauses.append("dataset_type=?")
            params.append(dataset_type)
        query = "SELECT * FROM source_reliability"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY source_id, dataset_type, window_days"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def resolved_reward_episodes_without_critic(self, critic_version: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.run_id
                FROM episodes e
                JOIN rewards r ON r.run_id=e.run_id AND r.reward_status='resolved'
                LEFT JOIN critic_records c
                    ON c.run_id=e.run_id AND c.critic_version=?
                WHERE e.status='completed' AND c.run_id IS NULL
                ORDER BY e.trade_date ASC
                """,
                (critic_version,),
            ).fetchall()
        episodes = []
        for row in rows:
            episode = self.load_episode(row["run_id"])
            if episode:
                episodes.append(episode)
        return episodes

    def _decisions_from_state(
        self,
        run_id: str,
        final_state: dict[str, Any],
        final_signal: str,
        *,
        trading_mode: str | None,
        horizon: str | None,
    ) -> list[DecisionRecordV1]:
        decisions: list[DecisionRecordV1] = []
        mapping = [
            ("research_manager", "Research Manager", final_state.get("investment_plan", "")),
            ("trader", "Trader", final_state.get("trader_investment_plan", "")),
            ("final", "Risk Manager", final_state.get("final_trade_decision", "")),
        ]
        for stage, agent_name, text in mapping:
            if not text:
                continue
            decision = parse_decision_text(
                str(text),
                run_id=run_id,
                stage=stage,
                agent_name=agent_name,
                trading_mode=trading_mode,
                horizon=horizon,
            )
            if stage == "final" and not decision.action and final_signal:
                decision = DecisionRecordV1(
                    **{
                        **asdict(decision),
                        "action": final_signal,
                        "parser_status": "partial",
                        "parser_warnings": [*decision.parser_warnings, "used_final_signal_fallback"],
                    }
                )
            decisions.append(decision)
        return decisions

    def _upsert_decision(self, conn: sqlite3.Connection, decision: DecisionRecordV1) -> None:
        conn.execute(
            """
            INSERT INTO decisions (
                run_id, stage, agent_name, action, confidence, advisory_rating,
                trading_mode, horizon, thesis, invalidation, risk_budget,
                position_plan, raw_text, parser_status, parser_warnings_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, stage, agent_name) DO UPDATE SET
                action=excluded.action,
                confidence=excluded.confidence,
                advisory_rating=excluded.advisory_rating,
                trading_mode=excluded.trading_mode,
                horizon=excluded.horizon,
                thesis=excluded.thesis,
                invalidation=excluded.invalidation,
                risk_budget=excluded.risk_budget,
                position_plan=excluded.position_plan,
                raw_text=excluded.raw_text,
                parser_status=excluded.parser_status,
                parser_warnings_json=excluded.parser_warnings_json
            """,
            (
                decision.run_id,
                decision.stage,
                decision.agent_name,
                decision.action,
                decision.confidence,
                decision.advisory_rating,
                decision.trading_mode,
                decision.horizon,
                decision.thesis,
                decision.invalidation,
                decision.risk_budget,
                decision.position_plan,
                decision.raw_text,
                decision.parser_status,
                _json_dump(decision.parser_warnings),
                _utc_now_iso(),
            ),
        )

    def _upsert_trace_span(self, conn: sqlite3.Connection, span: TraceSpanV1) -> None:
        conn.execute(
            """
            INSERT INTO trace_spans (
                run_id, span_id, parent_span_id, span_type, agent_name, node_name,
                tool_name, started_at, ended_at, status, metadata_json, artifact_ref,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, span_id) DO UPDATE SET
                parent_span_id=excluded.parent_span_id,
                span_type=excluded.span_type,
                agent_name=excluded.agent_name,
                node_name=excluded.node_name,
                tool_name=excluded.tool_name,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                artifact_ref=excluded.artifact_ref
            """,
            (
                span.run_id,
                span.span_id,
                span.parent_span_id,
                span.span_type,
                span.agent_name,
                span.node_name,
                span.tool_name,
                span.started_at,
                span.ended_at,
                span.status,
                _json_dump(span.metadata_json),
                span.artifact_ref,
                _utc_now_iso(),
            ),
        )

    def _add_memory_links_from_evidence(
        self,
        conn: sqlite3.Connection,
        memory_item_id: str,
        evidence: dict[str, Any],
    ) -> None:
        links = []
        for key, linked_type in (
            ("run_id", "episode"),
            ("reward_run_id", "reward"),
            ("critic_run_id", "critic"),
            ("manual_source_id", "manual"),
        ):
            value = evidence.get(key)
            if value:
                links.append((linked_type, str(value), "evidence"))
        for linked_type, linked_id, relation in evidence.get("links", []) if isinstance(evidence.get("links"), list) else []:
            links.append((str(linked_type), str(linked_id), str(relation or "evidence")))

        now = _utc_now_iso()
        for linked_type, linked_id, relation in links:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_links (
                    memory_item_id, linked_type, linked_id, relation, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_item_id, linked_type, linked_id, relation, _json_dump({}), now),
            )

    def _episode_from_row(self, row: sqlite3.Row) -> EpisodeRecord:
        return EpisodeRecord(
            run_id=row["run_id"],
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            status=row["status"],
            config=_json_load(row["config_json"], {}),
            selected_analysts=_json_load(row["selected_analysts_json"], []),
            metadata=_json_load(row["metadata_json"], {}),
            final_signal=row["final_signal"],
            audit_path=row["audit_path"],
            error_message=row["error_message"],
        )

    def _decision_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["parser_warnings"] = _json_load(item.pop("parser_warnings_json", None), [])
        item.pop("created_at", None)
        return item

    def _reward_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["components_json"] = _json_load(item.get("components_json"), {})
        return item

    def _trace_span_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata_json"] = _json_load(item.get("metadata_json"), {})
        item.pop("created_at", None)
        return item

    def _experiment_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["selected_analysts"] = _json_load(item.pop("selected_analysts_json", None), [])
        item["metadata_json"] = _json_load(item.get("metadata_json"), {})
        item.pop("created_at", None)
        item.pop("updated_at", None)
        return item

    def _memory_item_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["evidence_json"] = _json_load(item.get("evidence_json"), {})
        item["metadata_json"] = _json_load(item.get("metadata_json"), {})
        if not item.get("state"):
            item["state"] = item.get("status") or "candidate"
        return item

    def _critic_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["failure_tags"] = _json_load(item.pop("failure_tags_json", None), [])
        item["evidence_spans"] = _json_load(item.pop("evidence_spans_json", None), [])
        item["reward_snapshot"] = _json_load(item.pop("reward_snapshot_json", None), {})
        item["improvement_candidates"] = _json_load(
            item.pop("improvement_candidates_json", None),
            [],
        )
        return item

    def _quality_index_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["flags"] = _json_load(item.pop("flags_json", None), [])
        item["inputs"] = _json_load(item.pop("inputs_json", None), {})
        item.pop("created_at", None)
        item.pop("updated_at", None)
        return item

    def _run_index_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["selected_analysts"] = _json_load(item.pop("selected_analysts_json", None), [])
        item["critical_failures"] = _json_load(item.pop("critical_failures_json", None), [])
        item["stale_sources"] = _json_load(item.pop("stale_sources_json", None), [])
        item["fallback_sources"] = _json_load(item.pop("fallback_sources_json", None), [])
        item["flags"] = _json_load(item.pop("flags_json", None), [])
        item.pop("created_at", None)
        item.pop("updated_at", None)
        return item

    def _retrieval_pack_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["source_refs"] = _json_load(item.pop("source_refs_json", None), [])
        item["summary"] = _json_load(item.pop("summary_json", None), {})
        item.pop("created_at", None)
        item.pop("updated_at", None)
        return item

    def _retrieval_pack_item_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = _json_load(item.pop("payload_json", None), {})
        item.pop("created_at", None)
        return item

    def _quality_observation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["flags"] = _json_load(item.pop("flags_json", None), [])
        item.pop("created_at", None)
        item.pop("updated_at", None)
        return item

    def _quality_reconciliation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["flags"] = _json_load(item.pop("flags_json", None), [])
        item["source_refs"] = _json_load(item.pop("source_refs_json", None), [])
        item.pop("created_at", None)
        item.pop("updated_at", None)
        return item

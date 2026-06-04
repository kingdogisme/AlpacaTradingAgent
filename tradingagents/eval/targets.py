from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone, timedelta
from typing import Any

from .models import EvaluationOutcomeRecord, EvaluationTargetRecord
from .rewards import (
    PriceProvider,
    YFinancePriceProvider,
    benchmark_for,
    classification_reward,
    clip_reward,
    default_holding_days,
    neutral_band,
    oracle_label_for,
    pnl_reward_for,
)


ACTION_SET = {"BUY", "LONG", "SELL", "SHORT", "HOLD", "NEUTRAL"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvaluationTargetRepository:
    def __init__(self, ledger):
        self.ledger = ledger

    def upsert_target(self, target: EvaluationTargetRecord) -> None:
        now = utc_now_iso()
        created_at = target.created_at or now
        updated_at = target.updated_at or now
        with self.ledger._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_targets (
                    target_id, target_type, run_id, plan_id, candidate_id, symbol, action,
                    horizon, anchor_date, holding_days, source, trigger_status,
                    execution_status, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_id) DO UPDATE SET
                    target_type=excluded.target_type,
                    run_id=excluded.run_id,
                    plan_id=excluded.plan_id,
                    candidate_id=excluded.candidate_id,
                    symbol=excluded.symbol,
                    action=excluded.action,
                    horizon=excluded.horizon,
                    anchor_date=excluded.anchor_date,
                    holding_days=excluded.holding_days,
                    source=excluded.source,
                    trigger_status=excluded.trigger_status,
                    execution_status=excluded.execution_status,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    target.target_id,
                    target.target_type,
                    target.run_id,
                    target.plan_id,
                    target.candidate_id,
                    target.symbol.upper(),
                    target.action.upper(),
                    target.horizon,
                    target.anchor_date,
                    int(target.holding_days),
                    target.source,
                    target.trigger_status,
                    target.execution_status,
                    _json_dump(target.metadata_json),
                    created_at,
                    updated_at,
                ),
            )

    def list_targets(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("target_id", "target_type", "run_id", "plan_id", "candidate_id", "symbol", "horizon"):
            if filters.get(key):
                clauses.append(f"t.{key} = ?")
                params.append(filters[key])
        if filters.get("trigger_status"):
            clauses.append("t.trigger_status = ?")
            params.append(filters["trigger_status"])
        if filters.get("execution_status"):
            clauses.append("t.execution_status = ?")
            params.append(filters["execution_status"])
        if filters.get("since"):
            clauses.append("t.anchor_date >= ?")
            params.append(filters["since"])
        if filters.get("until"):
            clauses.append("t.anchor_date <= ?")
            params.append(filters["until"])
        if filters.get("pending_only"):
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1 FROM evaluation_outcomes o
                    WHERE o.target_id=t.target_id AND o.reward_version=?
                )
                """
            )
            params.append(filters.get("reward_version") or "v1_directional_alpha")
        query = "SELECT t.* FROM evaluation_targets t"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY t.anchor_date ASC, t.target_type ASC, t.symbol ASC"
        if filters.get("limit") is not None:
            query += " LIMIT ?"
            params.append(int(filters["limit"]))
        with self.ledger._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_target_from_row(row) for row in rows]

    def upsert_outcome(self, outcome: EvaluationOutcomeRecord) -> None:
        with self.ledger._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_outcomes (
                    target_id, reward_version, evaluation_status, holding_days,
                    raw_return, benchmark_return, alpha_return, oracle_label,
                    classification_reward, pnl_reward, reward_scalar, mfe, mae,
                    components_json, resolved_at, data_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_id, reward_version) DO UPDATE SET
                    evaluation_status=excluded.evaluation_status,
                    holding_days=excluded.holding_days,
                    raw_return=excluded.raw_return,
                    benchmark_return=excluded.benchmark_return,
                    alpha_return=excluded.alpha_return,
                    oracle_label=excluded.oracle_label,
                    classification_reward=excluded.classification_reward,
                    pnl_reward=excluded.pnl_reward,
                    reward_scalar=excluded.reward_scalar,
                    mfe=excluded.mfe,
                    mae=excluded.mae,
                    components_json=excluded.components_json,
                    resolved_at=excluded.resolved_at,
                    data_source=excluded.data_source
                """,
                (
                    outcome.target_id,
                    outcome.reward_version,
                    outcome.evaluation_status,
                    int(outcome.holding_days),
                    outcome.raw_return,
                    outcome.benchmark_return,
                    outcome.alpha_return,
                    outcome.oracle_label,
                    outcome.classification_reward,
                    outcome.pnl_reward,
                    outcome.reward_scalar,
                    outcome.mfe,
                    outcome.mae,
                    _json_dump(outcome.components_json),
                    outcome.resolved_at or utc_now_iso(),
                    outcome.data_source,
                ),
            )

    def list_outcomes(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("target_id", "reward_version", "evaluation_status"):
            if filters.get(key):
                clauses.append(f"o.{key} = ?")
                params.append(filters[key])
        if filters.get("target_type"):
            clauses.append("t.target_type = ?")
            params.append(filters["target_type"])
        if filters.get("symbol"):
            clauses.append("t.symbol = ?")
            params.append(filters["symbol"])
        if filters.get("horizon"):
            clauses.append("t.horizon = ?")
            params.append(filters["horizon"])
        query = """
            SELECT o.*, t.target_type, t.run_id, t.plan_id, t.candidate_id,
                   t.symbol, t.action, t.horizon, t.anchor_date, t.source,
                   t.trigger_status, t.execution_status, t.metadata_json AS target_metadata_json
            FROM evaluation_outcomes o
            JOIN evaluation_targets t ON t.target_id=o.target_id
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY t.anchor_date ASC, t.target_type ASC, t.symbol ASC"
        with self.ledger._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_outcome_from_row(row) for row in rows]


class EvaluationTargetBuilder:
    def __init__(
        self,
        ledger,
        *,
        trade_repository=None,
        alpha_repository=None,
        config: dict[str, Any] | None = None,
    ):
        self.ledger = ledger
        self.repository = EvaluationTargetRepository(ledger)
        self.trade_repository = trade_repository
        self.alpha_repository = alpha_repository
        self.config = config or {}

    def build_all(self, *, since: str | None = None) -> list[EvaluationTargetRecord]:
        targets: list[EvaluationTargetRecord] = []
        targets.extend(self.build_final_action_targets(since=since))
        targets.extend(self.build_trade_plan_targets())
        targets.extend(self.build_ad_candidate_targets())
        return targets

    def build_final_action_targets(self, *, since: str | None = None) -> list[EvaluationTargetRecord]:
        created: list[EvaluationTargetRecord] = []
        filters = {"status": "completed"}
        if since:
            filters["since"] = since
        for episode_record in self.ledger.list_episodes(filters):
            episode = self.ledger.load_episode(episode_record.run_id) or {}
            final = _decision_by_stage(episode, "final")
            action = _normalize_action((final or {}).get("action") or episode.get("final_signal"))
            if not action:
                continue
            horizon = (final or {}).get("horizon") or (episode.get("config") or {}).get("trading_horizon")
            target = EvaluationTargetRecord(
                target_id=f"eval:final_action:{episode_record.run_id}",
                target_type="final_action",
                run_id=episode_record.run_id,
                symbol=episode_record.symbol,
                action=action,
                horizon=horizon,
                anchor_date=episode_record.trade_date,
                holding_days=default_holding_days(horizon, self.config),
                source="episode_ledger",
                trigger_status="not_applicable",
                execution_status="not_ordered",
                metadata_json={
                    "final_signal": episode.get("final_signal"),
                    "confidence": (final or {}).get("confidence"),
                    "advisory_rating": (final or {}).get("advisory_rating"),
                },
            )
            self.repository.upsert_target(target)
            created.append(target)
        return created

    def build_trade_plan_targets(self) -> list[EvaluationTargetRecord]:
        if self.trade_repository is None:
            return []
        created: list[EvaluationTargetRecord] = []
        for plan in self.trade_repository.list_plans(limit=None):
            plan_target = EvaluationTargetRecord(
                target_id=f"eval:conditional_plan:{plan.plan_id}",
                target_type="conditional_plan",
                run_id=plan.source_run_id,
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                action=_normalize_action(plan.action.value) or "NEUTRAL",
                horizon=plan.horizon,
                anchor_date=_date_part(_episode_trade_date(self.ledger, plan.source_run_id) or plan.created_at),
                holding_days=default_holding_days(plan.horizon, self.config),
                source="trade_lifecycle",
                trigger_status=_plan_trigger_status(plan, self.trade_repository),
                execution_status=_plan_execution_status(plan),
                metadata_json={
                    "valid_until": plan.valid_until,
                    "plan_status": plan.status.value,
                    "trading_mode": plan.trading_mode,
                    "source_run_id": plan.source_run_id,
                },
            )
            self.repository.upsert_target(plan_target)
            created.append(plan_target)
            for event in self.trade_repository.list_events(plan.plan_id):
                if event.get("event_type") != "trigger_review_required":
                    continue
                observation = (event.get("payload") or {}).get("observation") or {}
                target = EvaluationTargetRecord(
                    target_id=f"eval:triggered_conditional_plan:{plan.plan_id}:{event.get('event_id')}",
                    target_type="triggered_conditional_plan",
                    run_id=plan.source_run_id,
                    plan_id=plan.plan_id,
                    symbol=plan.symbol,
                    action=_normalize_action(plan.action.value) or "NEUTRAL",
                    horizon=plan.horizon,
                    anchor_date=_date_part(observation.get("observed_at") or event.get("created_at") or plan.created_at),
                    holding_days=default_holding_days(plan.horizon, self.config),
                    source="trade_lifecycle",
                    trigger_status="triggered",
                    execution_status=_plan_execution_status(plan),
                    metadata_json={
                        "event_id": event.get("event_id"),
                        "event_created_at": event.get("created_at"),
                        "observation": observation,
                        "plan_status": plan.status.value,
                        "valid_until": plan.valid_until,
                    },
                )
                self.repository.upsert_target(target)
                created.append(target)
        return created

    def build_ad_candidate_targets(self) -> list[EvaluationTargetRecord]:
        if self.alpha_repository is None:
            return []
        created: list[EvaluationTargetRecord] = []
        for candidate in self.alpha_repository.list_candidates(tiers=None, status=None, limit=None):
            action, action_reason = _ad_action(candidate)
            horizon = self.config.get("alpha_discovery_ata_horizon", "position")
            target = EvaluationTargetRecord(
                target_id=f"eval:ad_candidate:{candidate['candidate_id']}",
                target_type="ad_candidate",
                candidate_id=candidate["candidate_id"],
                symbol=candidate["ticker"],
                action=action,
                horizon=str(horizon),
                anchor_date=_date_part(candidate.get("discovered_at") or candidate.get("updated_at")),
                holding_days=default_holding_days(str(horizon), self.config),
                source="alpha_discovery",
                trigger_status="not_applicable",
                execution_status="not_ordered",
                metadata_json={
                    "tier": candidate.get("tier"),
                    "alpha_score": candidate.get("alpha_score"),
                    "opportunity_type": candidate.get("opportunity_type"),
                    "direction_hint": candidate.get("direction_hint"),
                    "action_mapping_reason": action_reason,
                    "status": candidate.get("status"),
                },
            )
            self.repository.upsert_target(target)
            created.append(target)
        return created


class TargetAwareRewardResolver:
    def __init__(
        self,
        ledger,
        *,
        price_provider: PriceProvider | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.ledger = ledger
        self.repository = EvaluationTargetRepository(ledger)
        self.price_provider = price_provider or YFinancePriceProvider()
        self.config = config or {}
        self.reward_version = self.config.get("eval_reward_version", "v1_directional_alpha")

    def score_due_targets(self, *, as_of: str | None = None, filters: dict[str, Any] | None = None) -> list[EvaluationOutcomeRecord]:
        as_of_date = _parse_date(as_of) if as_of else date.today()
        target_filters = {**(filters or {}), "pending_only": True, "reward_version": self.reward_version}
        outcomes: list[EvaluationOutcomeRecord] = []
        for target in self.repository.list_targets(target_filters):
            outcome = self.resolve_target(target, as_of_date=as_of_date)
            self.repository.upsert_outcome(outcome)
            if outcome.evaluation_status == "resolved":
                outcomes.append(outcome)
        return outcomes

    def resolve_target(self, target: dict[str, Any], *, as_of_date: date) -> EvaluationOutcomeRecord:
        anchor_date = _parse_date(target["anchor_date"])
        holding_days = int(target.get("holding_days") or default_holding_days(target.get("horizon"), self.config))
        if anchor_date + timedelta(days=holding_days) > as_of_date:
            return EvaluationOutcomeRecord(
                target_id=target["target_id"],
                reward_version=self.reward_version,
                evaluation_status="not_mature",
                holding_days=holding_days,
                components_json={
                    "reason": "holding_period_not_elapsed",
                    "matures_at": (anchor_date + timedelta(days=holding_days)).isoformat(),
                    "as_of": as_of_date.isoformat(),
                    "trigger_status": target.get("trigger_status"),
                    "execution_status": target.get("execution_status"),
                },
                resolved_at=utc_now_iso(),
                data_source=type(self.price_provider).__name__,
            )
        raw_return = self.price_provider.fetch_return(target["symbol"], anchor_date, holding_days)
        if raw_return is None:
            return EvaluationOutcomeRecord(
                target_id=target["target_id"],
                reward_version=self.reward_version,
                evaluation_status="insufficient_data",
                holding_days=holding_days,
                components_json={
                    "reason": "missing_raw_return",
                    "symbol": target["symbol"],
                    "trigger_status": target.get("trigger_status"),
                    "execution_status": target.get("execution_status"),
                },
                resolved_at=utc_now_iso(),
                data_source=type(self.price_provider).__name__,
            )
        benchmark = benchmark_for(target["symbol"], self.config)
        benchmark_return = self.price_provider.fetch_return(benchmark, anchor_date, holding_days) if benchmark else None
        if benchmark and benchmark_return is None:
            return EvaluationOutcomeRecord(
                target_id=target["target_id"],
                reward_version=self.reward_version,
                evaluation_status="insufficient_data",
                holding_days=holding_days,
                raw_return=raw_return,
                components_json={
                    "reason": "missing_benchmark_return",
                    "symbol": target["symbol"],
                    "benchmark": benchmark,
                    "trigger_status": target.get("trigger_status"),
                    "execution_status": target.get("execution_status"),
                },
                resolved_at=utc_now_iso(),
                data_source=type(self.price_provider).__name__,
            )
        alpha_return = raw_return - benchmark_return if benchmark_return is not None else None
        return_used = alpha_return if alpha_return is not None else raw_return
        band = neutral_band(target.get("horizon"), self.config)
        action = _normalize_action(target.get("action"))
        mode = _mode_from_action(action)
        oracle = oracle_label_for(return_used, band, mode)
        class_reward = classification_reward(action, oracle)
        cost_bps = float(self.config.get("eval_transaction_cost_bps", 10))
        pnl_reward = pnl_reward_for(action, return_used, band, cost_bps)
        reward_scalar = clip_reward((class_reward + pnl_reward) / 2.0)
        missed = action in {"HOLD", "NEUTRAL"} and oracle in {"BUY", "LONG"}
        false_positive_buy = action in {"BUY", "LONG"} and oracle in {"SELL", "SHORT", "HOLD", "NEUTRAL"}
        avoided_downside = action in {"HOLD", "NEUTRAL"} and oracle in {"SELL", "SHORT"}
        return EvaluationOutcomeRecord(
            target_id=target["target_id"],
            reward_version=self.reward_version,
            evaluation_status="resolved",
            holding_days=holding_days,
            raw_return=raw_return,
            benchmark_return=benchmark_return,
            alpha_return=alpha_return,
            oracle_label=oracle,
            classification_reward=class_reward,
            pnl_reward=pnl_reward,
            reward_scalar=reward_scalar,
            components_json={
                "action": action,
                "return_used": return_used,
                "neutral_band": band,
                "benchmark": benchmark,
                "transaction_cost_bps": cost_bps,
                "trigger_status": target.get("trigger_status"),
                "execution_status": target.get("execution_status"),
                "missed_opportunity": missed,
                "false_positive_buy": false_positive_buy,
                "avoided_downside": avoided_downside,
                "target_type": target.get("target_type"),
                "source": target.get("source"),
            },
            resolved_at=utc_now_iso(),
            data_source=type(self.price_provider).__name__,
        )


def build_target_report(ledger, *, group_by: list[str] | None = None) -> list[dict[str, Any]]:
    group_by = group_by or ["target_type", "horizon", "symbol"]
    repo = EvaluationTargetRepository(ledger)
    targets = repo.list_targets()
    outcomes = repo.list_outcomes()
    outcome_by_target = {row["target_id"]: row for row in outcomes}
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        row = {**target, **(outcome_by_target.get(target["target_id"]) or {})}
        key = tuple(row.get(field) or "unknown" for field in group_by)
        groups[key].append(row)
    summaries = []
    for key, rows in groups.items():
        resolved = [row for row in rows if row.get("evaluation_status") == "resolved"]
        missed = [row for row in resolved if (row.get("components_json") or {}).get("missed_opportunity")]
        false_buy = [row for row in resolved if (row.get("components_json") or {}).get("false_positive_buy")]
        hits = [row for row in resolved if row.get("action") == row.get("oracle_label")]
        summaries.append(
            {
                "group": dict(zip(group_by, key)),
                "count": len(rows),
                "resolved": len(resolved),
                "pending": len(rows) - len(resolved),
                "hit_rate": len(hits) / len(resolved) if resolved else None,
                "avg_raw_return": _avg([row.get("raw_return") for row in resolved]),
                "avg_benchmark_return": _avg([row.get("benchmark_return") for row in resolved]),
                "avg_alpha_return": _avg([row.get("alpha_return") for row in resolved]),
                "avg_reward": _avg([row.get("reward_scalar") for row in resolved]),
                "missed_opportunity_count": len(missed),
                "missed_opportunity_rate": len(missed) / len(resolved) if resolved else None,
                "false_positive_buy_count": len(false_buy),
                "false_positive_buy_rate": len(false_buy) / len(resolved) if resolved else None,
                "trigger_status_distribution": dict(Counter(row.get("trigger_status") or "unknown" for row in rows)),
                "execution_status_distribution": dict(Counter(row.get("execution_status") or "unknown" for row in rows)),
            }
        )
    return summaries


def _target_from_row(row) -> dict[str, Any]:
    item = dict(row)
    item["metadata_json"] = _json_load(item.get("metadata_json"), {})
    return item


def _outcome_from_row(row) -> dict[str, Any]:
    item = dict(row)
    item["components_json"] = _json_load(item.get("components_json"), {})
    if "target_metadata_json" in item:
        item["target_metadata"] = _json_load(item.pop("target_metadata_json"), {})
    return item


def _json_dump(value: Any) -> str:
    import json

    return json.dumps(value if value is not None else {}, sort_keys=True, ensure_ascii=False)


def _json_load(value: str | None, fallback: Any | None = None) -> Any:
    import json

    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except Exception:
        return {} if fallback is None else fallback


def _decision_by_stage(episode: dict[str, Any], stage: str) -> dict[str, Any] | None:
    for decision in episode.get("decisions") or []:
        if decision.get("stage") == stage:
            return decision
    return None


def _normalize_action(value: Any) -> str | None:
    action = str(getattr(value, "value", value) or "").upper()
    return action if action in ACTION_SET else None


def _episode_trade_date(ledger, run_id: str | None) -> str | None:
    if not run_id:
        return None
    episode = ledger.load_episode(run_id)
    return episode.get("trade_date") if episode else None


def _date_part(value: Any) -> str:
    text = str(value or "")
    if "T" in text:
        return text.split("T", 1)[0]
    if " " in text:
        return text.split(" ", 1)[0]
    return text[:10]


def _parse_date(value: str) -> date:
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _mode_from_action(action: str | None) -> str:
    return "trading" if action in {"LONG", "NEUTRAL", "SHORT"} else "investment"


def _plan_trigger_status(plan, repository) -> str:
    if any(event.get("event_type") == "trigger_review_required" for event in repository.list_events(plan.plan_id)):
        return "triggered"
    status = getattr(plan.status, "value", str(plan.status))
    if status == "expired":
        return "expired"
    return "not_triggered"


def _plan_execution_status(plan) -> str:
    status = getattr(plan.status, "value", str(plan.status))
    if status == "executed":
        return "executed"
    if status in {"needs_review", "triggered", "needs_reconciliation"}:
        return "needs_review"
    if status in {"cancelled", "rejected", "superseded"}:
        return "cancelled"
    return "not_ordered"


def _ad_action(candidate: dict[str, Any]) -> tuple[str, str]:
    direction = str(candidate.get("direction_hint") or "").lower()
    opportunity_type = str(candidate.get("opportunity_type") or "").lower()
    if direction in {"bullish", "long", "buy"}:
        return "BUY", "direction_hint_bullish"
    if direction in {"bearish", "short", "sell"}:
        return "SELL", "direction_hint_bearish"
    if direction == "avoid" or opportunity_type == "avoid":
        return "HOLD", "avoid_maps_to_hold"
    return "NEUTRAL", "uncertain_maps_to_neutral"


def _avg(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from .models import ConditionalTradePlan, TradePlanEvent, TradePlanStatus
from .repository import TradePlanRepository


MONITORABLE_ACTIONS = {"BUY", "LONG", "SELL", "SHORT"}


def monitor_status(
    repository: TradePlanRepository,
    *,
    stale_after_seconds: int = 600,
    lock_path: str | Path | None = None,
) -> dict[str, Any]:
    latest_heartbeat = repository.latest_monitor_event("monitor_heartbeat")
    heartbeat_age_seconds = _event_age_seconds(latest_heartbeat)
    heartbeat_stale = heartbeat_age_seconds is None or heartbeat_age_seconds > stale_after_seconds
    resolved_lock_path = (
        Path(lock_path).expanduser()
        if lock_path
        else repository.path.with_name(f"{repository.path.name}.monitor.lock")
    )
    monitor_lock_held = _lock_held(resolved_lock_path)
    open_plans = repository.list_plans(
        statuses=[TradePlanStatus.ACTIVE, TradePlanStatus.NEEDS_REVIEW],
        limit=None,
    )
    candidates = [
        summarize_plan(plan, repository)
        for plan in open_plans
        if _is_monitorable_candidate(plan)
    ]
    needs_review = [
        summarize_plan(plan, repository)
        for plan in open_plans
        if plan.status == TradePlanStatus.NEEDS_REVIEW
    ]
    return {
        "db_path": str(repository.path),
        "monitor_running": bool(monitor_lock_held),
        "monitor_state": _monitor_state(
            lock_held=monitor_lock_held,
            latest_heartbeat=latest_heartbeat,
            heartbeat_stale=heartbeat_stale,
        ),
        "monitor_lock_path": str(resolved_lock_path),
        "monitor_lock_held": monitor_lock_held,
        "monitor_running_evidence": _compact_event(latest_heartbeat),
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "heartbeat_stale": heartbeat_stale,
        "stale_after_seconds": stale_after_seconds,
        "open_plan_count": len(open_plans),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "needs_review_count": len(needs_review),
        "needs_review": needs_review,
    }


def monitor_preflight(
    repository: TradePlanRepository,
    *,
    config: dict[str, Any] | None = None,
    lock_path: str | Path | None = None,
) -> dict[str, Any]:
    config = config or {}
    status = monitor_status(
        repository,
        stale_after_seconds=int(config.get("trade_monitor_heartbeat_stale_seconds") or 600),
        lock_path=lock_path,
    )
    alpaca_key_present = bool(os.getenv("ALPACA_API_KEY") or config.get("alpaca_api_key"))
    alpaca_secret_present = bool(os.getenv("ALPACA_SECRET_KEY") or config.get("alpaca_secret_key"))
    webhook_configured = bool(
        os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_WEBHOOK_URL")
        or config.get("trade_monitor_review_webhook_url")
    )
    im_channel = os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_CHANNEL") or config.get(
        "trade_monitor_review_im_channel"
    )
    im_target = os.getenv("TRADINGAGENTS_TRADE_MONITOR_REVIEW_IM_TARGET") or config.get("trade_monitor_review_im_target")
    im_configured = bool(im_channel and im_target)
    checks = {
        "db_parent_exists": repository.path.parent.exists(),
        "db_parent_writable": os.access(repository.path.parent, os.W_OK),
        "alpaca_api_key_present": alpaca_key_present,
        "alpaca_secret_key_present": alpaca_secret_present,
        "alpaca_credentials_ready": alpaca_key_present and alpaca_secret_present,
        "review_webhook_configured": webhook_configured,
        "review_im_configured": im_configured,
        "review_notification_configured": webhook_configured or im_configured,
        "has_monitorable_candidates": status["candidate_count"] > 0,
    }
    required = [
        "db_parent_exists",
        "db_parent_writable",
        "alpaca_credentials_ready",
        "has_monitorable_candidates",
    ]
    blocking = [name for name in required if not checks[name]]
    warnings = []
    if not checks["review_notification_configured"]:
        warnings.append("review_notification_not_configured")
    return {
        "ready": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
        "status": status,
    }


def summarize_plan(
    plan: ConditionalTradePlan,
    repository: TradePlanRepository,
    *,
    include_events: bool = False,
    include_validations: bool = False,
) -> dict[str, Any]:
    latest_event = repository.latest_event(plan.plan_id)
    latest_validation = repository.latest_validation(plan.plan_id)
    progress = _progress_state(plan, latest_event=latest_event, latest_validation=latest_validation)
    summary = {
        "plan_id": plan.plan_id,
        "symbol": plan.symbol,
        "action": plan.action.value,
        "side": plan.side,
        "status": plan.status.value,
        "progress": progress,
        "trigger": plan.trigger.model_dump(mode="json"),
        "invalidation": plan.invalidation.model_dump(mode="json"),
        "valid_until": plan.valid_until,
        "risk_budget": plan.risk_budget.model_dump(mode="json"),
        "execution_policy": plan.execution_policy.model_dump(mode="json"),
        "max_notional": plan.max_notional,
        "source_run_id": plan.source_run_id,
        "source_audit_path": plan.source_audit_path,
        "horizon": plan.horizon,
        "trading_mode": plan.trading_mode,
        "metadata": plan.metadata,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "latest_event": _compact_event(latest_event),
        "latest_validation": _compact_validation(latest_validation),
    }
    if include_events:
        summary["events"] = repository.list_events(plan.plan_id)
    if include_validations:
        summary["validations"] = repository.list_validations(plan.plan_id, limit=None)
    return summary


def plan_health(repository: TradePlanRepository) -> dict[str, Any]:
    plans = repository.list_plans(limit=None)
    counts_by_status: dict[str, int] = {}
    counts_by_progress: dict[str, int] = {}
    stale_active: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for plan in plans:
        status = plan.status.value
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        latest_event = repository.latest_event(plan.plan_id)
        latest_validation = repository.latest_validation(plan.plan_id)
        progress = _progress_state(plan, latest_event=latest_event, latest_validation=latest_validation)
        counts_by_progress[progress] = counts_by_progress.get(progress, 0) + 1
        compact = {
            "plan_id": plan.plan_id,
            "symbol": plan.symbol,
            "status": status,
            "progress": progress,
            "source_run_id": plan.source_run_id,
            "latest_event": _compact_event(latest_event),
            "latest_validation": _compact_validation(latest_validation),
        }
        if plan.status in {TradePlanStatus.TRIGGERED, TradePlanStatus.NEEDS_RECONCILIATION}:
            reconciliation.append(compact)
        if plan.status == TradePlanStatus.ACTIVE and plan.is_expired(now):
            stale_active.append(compact)
    recent = [
        summarize_plan(plan, repository)
        for plan in repository.list_plans(limit=10)
    ]
    return {
        "db_path": str(repository.path),
        "total_plans": len(plans),
        "counts_by_status": counts_by_status,
        "counts_by_progress": counts_by_progress,
        "stale_active": stale_active,
        "needs_reconciliation": reconciliation,
        "recent_plans": recent,
    }


def reconcile_plans(repository: TradePlanRepository) -> dict[str, Any]:
    candidates = repository.list_plans(
        statuses=[TradePlanStatus.TRIGGERED, TradePlanStatus.NEEDS_RECONCILIATION],
        limit=None,
    )
    reconciled: list[dict[str, Any]] = []
    for plan in candidates:
        events = repository.list_events(plan.plan_id)
        order_events = [event for event in events if event["event_type"] == "order_result"]
        latest_validation = repository.latest_validation(plan.plan_id)
        if order_events:
            latest_order = order_events[-1]
            next_status = TradePlanStatus.EXECUTED if latest_order["status"] == "ok" else TradePlanStatus.REJECTED
            updated = repository.force_status(
                plan.plan_id,
                next_status,
                reason="reconciled from persisted order_result event",
                payload={"order_event_id": latest_order["event_id"]},
            )
            reconciled.append(
                {
                    "plan_id": plan.plan_id,
                    "symbol": plan.symbol,
                    "action": "status_updated",
                    "status": updated.status.value if updated else next_status.value,
                }
            )
            continue
        repository.force_status(
            plan.plan_id,
            TradePlanStatus.NEEDS_RECONCILIATION,
            reason="triggered plan has validation but no order_result; manual review required",
            payload={
                "latest_validation_id": latest_validation.get("validation_id") if latest_validation else None,
                "idempotency_key": (latest_validation.get("execution_policy") or {}).get("idempotency_key")
                if latest_validation
                else None,
                "client_order_id": (latest_validation.get("execution_policy") or {}).get("client_order_id")
                if latest_validation
                else None,
            },
        )
        reconciled.append(
            {
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "action": "manual_review_required",
                "status": TradePlanStatus.NEEDS_RECONCILIATION.value,
            }
        )
    return {"checked": len(candidates), "reconciled": reconciled}


def record_manual_action(
    repository: TradePlanRepository,
    *,
    plan_id: str,
    action: str,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> ConditionalTradePlan | None:
    normalized = action.strip().lower().replace("_", "-")
    status_map = {
        "cancel": TradePlanStatus.CANCELLED,
        "reject": TradePlanStatus.REJECTED,
        "mark-executed": TradePlanStatus.EXECUTED,
        "mark-no-execution": TradePlanStatus.CANCELLED,
        "needs-reconciliation": TradePlanStatus.NEEDS_RECONCILIATION,
    }
    plan = repository.get_plan(plan_id)
    if plan is None:
        return None
    if normalized not in status_map:
        raise ValueError(f"unsupported manual action: {action}")
    target = status_map[normalized]
    updated = repository.force_status(
        plan_id,
        target,
        reason=reason or f"manual action: {normalized}",
        payload={"manual_action": normalized, **(payload or {})},
    )
    repository.append_event(
        TradePlanEvent(
            plan_id=plan_id,
            event_type="manual_action",
            status=target.value,
            message=reason or f"manual action: {normalized}",
            payload={"action": normalized, "target_status": target.value, **(payload or {})},
        )
    )
    return updated


def _progress_state(
    plan: ConditionalTradePlan,
    *,
    latest_event: dict[str, Any] | None,
    latest_validation: dict[str, Any] | None,
) -> str:
    if plan.status == TradePlanStatus.ACTIVE:
        if latest_validation and latest_validation.get("passed") is False:
            return "validation_rejected"
        if latest_event and latest_event.get("event_type") == "monitor_observation":
            return "waiting_trigger"
        return "waiting_trigger"
    if plan.status == TradePlanStatus.TRIGGERED:
        return "met_pending_order_result"
    if plan.status == TradePlanStatus.NEEDS_REVIEW:
        return "trigger_review_required"
    if plan.status == TradePlanStatus.NEEDS_RECONCILIATION:
        return "needs_reconciliation"
    if plan.status == TradePlanStatus.EXECUTED:
        return "executed"
    if plan.status == TradePlanStatus.EXPIRED:
        return "expired"
    if plan.status == TradePlanStatus.REJECTED:
        return "validation_rejected" if latest_validation else "rejected"
    if plan.status == TradePlanStatus.CANCELLED:
        return "cancelled"
    if plan.status == TradePlanStatus.SUPERSEDED:
        return "superseded"
    return plan.status.value


def _compact_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "status": event.get("status"),
        "message": event.get("message"),
        "created_at": event.get("created_at"),
    }


def _event_age_seconds(event: dict[str, Any] | None) -> float | None:
    if not event or not event.get("created_at"):
        return None
    try:
        created = datetime.fromisoformat(str(event["created_at"]))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds(), 0.0)


def _lock_held(lock_path: Path) -> bool | None:
    if not lock_path.exists():
        return False
    try:
        import fcntl

        with lock_path.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        return False
    except OSError:
        return None


def _monitor_state(
    *,
    lock_held: bool | None,
    latest_heartbeat: dict[str, Any] | None,
    heartbeat_stale: bool,
) -> str:
    if lock_held and latest_heartbeat and not heartbeat_stale:
        return "running"
    if lock_held:
        return "lock_held_but_heartbeat_stale"
    if latest_heartbeat and not heartbeat_stale:
        return "recent_heartbeat_no_running_lock"
    if latest_heartbeat:
        return "stopped_or_stale"
    return "never_seen"


def _is_monitorable_candidate(plan: ConditionalTradePlan) -> bool:
    if plan.status != TradePlanStatus.ACTIVE:
        return False
    if plan.action.value not in MONITORABLE_ACTIONS:
        return False
    return True


def _compact_validation(validation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not validation:
        return None
    return {
        "validation_id": validation.get("validation_id"),
        "passed": validation.get("passed"),
        "decision": validation.get("decision"),
        "reason_code": validation.get("reason_code"),
        "reasons": validation.get("reasons"),
        "created_at": validation.get("created_at"),
        "execution_policy": validation.get("execution_policy"),
    }

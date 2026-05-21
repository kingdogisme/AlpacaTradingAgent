from __future__ import annotations

import atexit
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import uuid
from typing import Any, Dict, Optional

REPORT_OUTPUT_TYPES = {
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "macro_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
    "trading_horizon",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_for_path(value: str) -> str:
    sanitized = re.sub(r"[^\w\-.]+", "_", value.strip())
    return sanitized or "unknown"


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _empty_llm_usage_summary() -> Dict[str, Any]:
    return {
        "llm_call_events": 0,
        "total_llm_time_seconds": 0.0,
        "total_llm_input_chars": 0,
        "total_llm_output_chars": 0,
        "total_llm_input_tokens": 0,
        "total_llm_cache_hit_tokens": 0,
        "total_llm_cache_miss_tokens": 0,
        "total_llm_cache_creation_tokens": 0,
        "total_llm_output_tokens": 0,
        "total_llm_reasoning_tokens": 0,
        "total_llm_tokens": 0,
    }


def _empty_data_quality_summary() -> Dict[str, Any]:
    return {
        "quality_pass": 0,
        "quality_warn": 0,
        "quality_fail": 0,
        "quality_unknown": 0,
        "stale_sources": [],
        "fallback_sources": [],
        "critical_failures": [],
    }


def _add_llm_usage_summary(summary: Dict[str, Any], payload: Dict[str, Any]) -> None:
    summary["llm_call_events"] += 1
    summary["total_llm_time_seconds"] += float(
        (payload or {}).get("latency_seconds", 0.0) or 0.0
    )
    summary["total_llm_input_chars"] += int(
        (payload or {}).get("input_chars", 0) or 0
    )
    summary["total_llm_output_chars"] += int(
        (payload or {}).get("output_chars", 0) or 0
    )
    usage = (payload or {}).get("usage", {}) or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cache_hit_tokens = int(
        usage.get("cache_hit_tokens", usage.get("cached_tokens", 0)) or 0
    )
    cache_creation_tokens = int(usage.get("cache_creation_tokens", 0) or 0)
    cache_miss_tokens = int(
        usage.get(
            "cache_miss_tokens",
            max(input_tokens - cache_hit_tokens - cache_creation_tokens, 0),
        )
        or 0
    )
    summary["total_llm_input_tokens"] += int(input_tokens)
    summary["total_llm_cache_hit_tokens"] += int(cache_hit_tokens)
    summary["total_llm_cache_miss_tokens"] += int(cache_miss_tokens)
    summary["total_llm_cache_creation_tokens"] += int(cache_creation_tokens)
    summary["total_llm_output_tokens"] += int(usage.get("output_tokens", 0) or 0)
    summary["total_llm_reasoning_tokens"] += int(usage.get("reasoning_tokens", 0) or 0)
    summary["total_llm_tokens"] += int(usage.get("total_tokens", 0) or 0)


class RunAuditLogger:
    """
    Persist a complete audit trail for each analysis run.

    Logs are written incrementally so partial runs are still debuggable if a run fails.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._active_runs_by_symbol: Dict[str, str] = {}
        self._active_runs: Dict[str, Dict[str, Any]] = {}
        self._completed_run_paths: Dict[str, str] = {}
        self._recover_stale_running_logs()
        atexit.register(self._close_active_runs_on_exit)

    def _recover_stale_running_logs(self) -> None:
        """Mark stale on-disk runs as aborted if they were left in running state."""
        root = Path("eval_results")
        if not root.exists():
            return

        recovered = 0
        for path in root.glob("*/TradingAgentsStrategy_logs/runs/*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue

            if payload.get("status") != "running" or payload.get("ended_at"):
                continue

            payload["status"] = "aborted"
            payload["ended_at"] = _utc_now_iso()
            summary = payload.setdefault("summary", {})
            if not summary.get("error_message"):
                summary["error_message"] = (
                    "Recovered stale running log after process termination."
                )
            summary["error_events"] = int(summary.get("error_events", 0) or 0) + 1

            try:
                with path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
                recovered += 1
            except Exception:
                continue

        if recovered:
            print(f"[RUN_LOG] Recovered {recovered} stale running log(s)")

    def _close_active_runs_on_exit(self) -> None:
        """Best-effort closure for in-flight runs when process exits unexpectedly."""
        try:
            with self._lock:
                if not self._active_runs:
                    return

                for run_id, run_data in list(self._active_runs.items()):
                    if run_data.get("ended_at"):
                        continue

                    run_data["ended_at"] = _utc_now_iso()
                    if run_data.get("status") == "running":
                        run_data["status"] = "aborted"

                    summary = run_data.setdefault("summary", {})
                    if not summary.get("error_message"):
                        summary["error_message"] = (
                            "Run terminated before finish_run was called (process exit/termination)."
                        )
                    summary["error_events"] = int(summary.get("error_events", 0) or 0) + 1
                    self._snapshot_latest_agent_outputs_unlocked(run_data)

                    self._flush_unlocked(run_id)

                self._active_runs.clear()
                self._active_runs_by_symbol.clear()
        except Exception:
            # Exit handlers must never raise.
            return

    def start_run(
        self,
        symbol: str,
        trade_date: str,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            safe_symbol = _sanitize_for_path(symbol or "unknown")
            run_uuid = uuid.uuid4().hex[:10]
            run_id = f"{trade_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_uuid}"

            run_dir = Path("eval_results") / safe_symbol / "TradingAgentsStrategy_logs" / "runs"
            run_dir.mkdir(parents=True, exist_ok=True)
            file_path = run_dir / f"{run_id}.json"

            run_data: Dict[str, Any] = {
                "run_id": run_id,
                "symbol": symbol,
                "trade_date": str(trade_date),
                "file_path": str(file_path),
                "started_at": _utc_now_iso(),
                "ended_at": None,
                "status": "running",
                "config": _json_safe(config or {}),
                "metadata": _json_safe(metadata or {}),
                "events": [],
                "snapshots": {},
                "summary": {
                    "prompt_events": 0,
                    "tool_events": 0,
                    "llm_call_events": 0,
                    "agent_output_events": 0,
                    "node_events": 0,
                    "tool_retry_events": 0,
                    "error_events": 0,
                    "warning_events": 0,
                    "timeout_tool_events": 0,
                    "degraded_tool_events": 0,
                    "total_prompt_chars": 0,
                    "total_tool_time_seconds": 0.0,
                    "total_tool_output_chars": 0,
                    "suspect_tool_events": 0,
                    **_empty_llm_usage_summary(),
                    **_empty_data_quality_summary(),
                    "llm_usage_by_model": {},
                    "llm_usage_by_role": {},
                },
            }

            self._active_runs[run_id] = run_data
            self._active_runs_by_symbol[symbol] = run_id
            self._flush_unlocked(run_id)
            print(f"[RUN_LOG] Started run {run_id} -> {file_path}")
            return run_id

    def _resolve_run_id(self, run_id: Optional[str], symbol: Optional[str]) -> Optional[str]:
        if run_id and run_id in self._active_runs:
            return run_id
        if symbol and symbol in self._active_runs_by_symbol:
            return self._active_runs_by_symbol[symbol]
        if len(self._active_runs) == 1:
            return next(iter(self._active_runs.keys()))
        return None

    def get_active_run_id(self, symbol: Optional[str] = None) -> Optional[str]:
        with self._lock:
            return self._resolve_run_id(None, symbol)

    def get_run_file_path(
        self,
        run_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Optional[str]:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id, symbol)
            if not resolved_run_id:
                return None
            run_data = self._active_runs.get(resolved_run_id)
            if not run_data:
                return self._completed_run_paths.get(resolved_run_id)
            return run_data.get("file_path")

    def log_event(
        self,
        event_type: str,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id, symbol)
            if not resolved_run_id:
                return

            run_data = self._active_runs.get(resolved_run_id)
            if not run_data:
                return

            event = {
                "timestamp": _utc_now_iso(),
                "type": event_type,
                "payload": _json_safe(payload or {}),
            }
            run_data["events"].append(event)

            if event_type == "prompt":
                run_data["summary"]["prompt_events"] += 1
                prompt_text = (payload or {}).get("prompt_text", "")
                run_data["summary"]["total_prompt_chars"] += len(str(prompt_text))
            elif event_type == "tool_call":
                run_data["summary"]["tool_events"] += 1
                tool_time = (payload or {}).get("execution_time_seconds", 0.0)
                run_data["summary"]["total_tool_time_seconds"] += float(tool_time or 0.0)
                output = (payload or {}).get("output", "")
                run_data["summary"]["total_tool_output_chars"] += len(str(output or ""))
                quality = (payload or {}).get("quality_details", {}) or {}
                data_quality = quality.get("data_quality", {}) if isinstance(quality, dict) else {}
                status = str((payload or {}).get("status", "") or "").lower()
                flags = quality.get("flags", []) or []
                if bool(quality.get("is_suspect", False)):
                    run_data["summary"]["suspect_tool_events"] += 1
                if status == "timeout" or "timeout" in flags:
                    run_data["summary"]["timeout_tool_events"] += 1
                if status in ("degraded", "timeout") or bool(quality.get("is_suspect", False)) or flags:
                    run_data["summary"]["degraded_tool_events"] += 1
                    run_data["summary"]["warning_events"] += 1
                if isinstance(data_quality, dict) and data_quality:
                    quality_status = str(data_quality.get("status") or "unknown").lower()
                    if quality_status not in ("pass", "warn", "fail", "unknown"):
                        quality_status = "unknown"
                    run_data["summary"][f"quality_{quality_status}"] += 1

                    source_id = str(data_quality.get("source_id") or "unknown")
                    if "stale_source" in (data_quality.get("flags") or []):
                        stale_sources = set(run_data["summary"].get("stale_sources") or [])
                        stale_sources.add(source_id)
                        run_data["summary"]["stale_sources"] = sorted(stale_sources)
                    if data_quality.get("fallback_from"):
                        fallback_sources = set(run_data["summary"].get("fallback_sources") or [])
                        fallback_sources.add(source_id)
                        run_data["summary"]["fallback_sources"] = sorted(fallback_sources)
                    if quality_status == "fail" and data_quality.get("criticality") == "critical":
                        critical_failures = set(run_data["summary"].get("critical_failures") or [])
                        critical_failures.add(source_id)
                        run_data["summary"]["critical_failures"] = sorted(critical_failures)
            elif event_type == "llm_call":
                payload = payload or {}
                _add_llm_usage_summary(run_data["summary"], payload)

                model_key = str(payload.get("model") or "unknown")
                by_model = run_data["summary"].setdefault("llm_usage_by_model", {})
                model_summary = by_model.setdefault(model_key, _empty_llm_usage_summary())
                _add_llm_usage_summary(model_summary, payload)

                role_key = str(payload.get("model_role") or "unknown")
                by_role = run_data["summary"].setdefault("llm_usage_by_role", {})
                role_summary = by_role.setdefault(role_key, _empty_llm_usage_summary())
                _add_llm_usage_summary(role_summary, payload)
            elif event_type == "agent_output":
                run_data["summary"]["agent_output_events"] += 1
            elif event_type == "node_execution":
                run_data["summary"]["node_events"] += 1
            elif event_type == "tool_retry":
                run_data["summary"]["tool_retry_events"] += 1

            if event_type in ("error", "tool_error", "node_error"):
                run_data["summary"]["error_events"] += 1

            self._flush_unlocked(resolved_run_id)

    def log_prompt(
        self,
        report_type: str,
        prompt_text: str,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.log_event(
            event_type="prompt",
            symbol=symbol,
            run_id=run_id,
            payload={
                "report_type": report_type,
                "prompt_text": prompt_text,
                "metadata": metadata or {},
            },
        )

    def log_tool_call(
        self,
        tool_name: str,
        inputs: Dict[str, Any],
        output: Any,
        status: str,
        execution_time_seconds: float,
        agent_type: Optional[str] = None,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
        error_details: Optional[Dict[str, Any]] = None,
        quality_details: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> None:
        self.log_event(
            event_type="tool_call",
            symbol=symbol,
            run_id=run_id,
            payload={
                "tool_name": tool_name,
                "agent_type": agent_type,
                "inputs": inputs,
                "output": output,
                "status": status,
                "execution_time_seconds": execution_time_seconds,
                "error_details": error_details or {},
                "quality_details": quality_details or {},
                "retry_count": retry_count,
            },
        )

    def log_agent_output(
        self,
        output_type: str,
        content: Any,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.log_event(
            event_type="agent_output",
            symbol=symbol,
            run_id=run_id,
            payload={
                "output_type": output_type,
                "content": content,
                "metadata": metadata or {},
            },
        )

    def log_state_snapshot(
        self,
        stage: str,
        snapshot: Dict[str, Any],
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id, symbol)
            if not resolved_run_id:
                return

            run_data = self._active_runs.get(resolved_run_id)
            if not run_data:
                return

            run_data["snapshots"][stage] = _json_safe(snapshot)
            self._flush_unlocked(resolved_run_id)

    def finish_run(
        self,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
        status: str = "completed",
        final_state: Optional[Dict[str, Any]] = None,
        final_signal: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id, symbol)
            if not resolved_run_id:
                return

            run_data = self._active_runs.get(resolved_run_id)
            if not run_data:
                return

            run_data["ended_at"] = _utc_now_iso()
            run_data["status"] = status

            if final_state is not None:
                run_data["snapshots"]["final_state"] = _json_safe(final_state)
            if final_signal is not None:
                run_data["summary"]["final_signal"] = final_signal
            if error_message:
                run_data["summary"]["error_message"] = error_message
                run_data["summary"]["error_events"] += 1

            self._flush_unlocked(resolved_run_id)
            file_path = run_data.get("file_path", "")
            print(
                f"[RUN_LOG] Finished run {resolved_run_id} ({status}) -> "
                f"{file_path}"
            )

            symbol_key = run_data.get("symbol")
            if symbol_key in self._active_runs_by_symbol:
                if self._active_runs_by_symbol[symbol_key] == resolved_run_id:
                    del self._active_runs_by_symbol[symbol_key]
            self._completed_run_paths[resolved_run_id] = file_path
            del self._active_runs[resolved_run_id]

    def _snapshot_latest_agent_outputs_unlocked(self, run_data: Dict[str, Any]) -> None:
        """Save last visible reports so aborted runs can still be inspected/restored."""
        latest_outputs: Dict[str, Any] = {}
        for event in run_data.get("events", []):
            if event.get("type") != "agent_output":
                continue
            payload = event.get("payload") or {}
            output_type = payload.get("output_type")
            if output_type in REPORT_OUTPUT_TYPES and payload.get("content"):
                latest_outputs[output_type] = payload.get("content")

        if not latest_outputs:
            return

        snapshots = run_data.setdefault("snapshots", {})
        snapshots["latest_agent_outputs"] = _json_safe(latest_outputs)
        if "final_state" not in snapshots and latest_outputs.get("final_trade_decision"):
            snapshots["final_state"] = _json_safe(latest_outputs)

    def _flush_unlocked(self, run_id: str) -> None:
        run_data = self._active_runs.get(run_id)
        if not run_data:
            return

        safe_symbol = _sanitize_for_path(run_data.get("symbol") or "unknown")
        path = Path("eval_results") / safe_symbol / "TradingAgentsStrategy_logs" / "runs" / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(run_data, f, indent=2, ensure_ascii=False)


_RUN_AUDIT_LOGGER = RunAuditLogger()


def get_run_audit_logger() -> RunAuditLogger:
    return _RUN_AUDIT_LOGGER

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


OPENAI_SOURCE_POLICIES = {"eager", "fallback", "disabled"}
POINT_IN_TIME_SOURCE_POLICIES = {"auto", "live", "historical"}


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def point_in_time_source_policy(config: dict[str, Any] | None) -> str:
    policy = str((config or {}).get("point_in_time_source_policy", "auto") or "auto").strip().lower()
    return policy if policy in POINT_IN_TIME_SOURCE_POLICIES else "auto"


def is_point_in_time_mode(trade_date: object, config: dict[str, Any] | None = None) -> bool:
    policy = point_in_time_source_policy(config)
    if policy == "historical":
        return True
    if policy == "live":
        return False
    parsed = _parse_date(trade_date)
    if parsed is None:
        return False
    today = datetime.now(timezone.utc).date()
    return parsed < today


def point_in_time_source_note(trade_date: object, config: dict[str, Any] | None = None) -> str:
    if is_point_in_time_mode(trade_date, config):
        return (
            "Point-in-time mode is active because the analysis date is historical. "
            "Live-only sources are disabled to avoid future-data leakage."
        )
    return "Live-source mode is active for the analysis date."


def openai_sources_policy(config: dict[str, Any] | None) -> str:
    policy = str((config or {}).get("openai_sources_policy", "fallback") or "fallback").strip().lower()
    return policy if policy in OPENAI_SOURCE_POLICIES else "fallback"


def should_bind_openai_source(
    config: dict[str, Any] | None,
    *,
    source_type: str,
    openai_available: bool,
    non_openai_available: bool,
) -> bool:
    if not openai_available:
        return False
    policy = openai_sources_policy(config)
    if policy == "disabled":
        return False
    if policy == "eager":
        return True
    if not bool((config or {}).get("skip_openai_when_non_openai_sufficient", True)):
        return True
    return not non_openai_available


def openai_source_decision_reason(
    config: dict[str, Any] | None,
    *,
    source_type: str,
    openai_available: bool,
    non_openai_available: bool,
) -> str:
    policy = openai_sources_policy(config)
    if not openai_available:
        return f"{source_type}: OpenAI web-search source unavailable"
    if policy == "disabled":
        return f"{source_type}: OpenAI web-search source disabled by policy"
    if policy == "eager":
        return f"{source_type}: OpenAI web-search source bound by eager policy"
    if non_openai_available and bool((config or {}).get("skip_openai_when_non_openai_sufficient", True)):
        return f"{source_type}: OpenAI web-search source skipped because non-OpenAI sources are available"
    return f"{source_type}: OpenAI web-search source bound as fallback"


def openai_source_skip_reason(
    config: dict[str, Any] | None,
    *,
    openai_available: bool,
    non_openai_available: bool,
    point_in_time_mode: bool = False,
) -> str | None:
    if not openai_available:
        return None
    if point_in_time_mode:
        return "point_in_time_mode"
    policy = openai_sources_policy(config)
    if policy == "disabled":
        return "policy_disabled"
    if (
        policy == "fallback"
        and non_openai_available
        and bool((config or {}).get("skip_openai_when_non_openai_sufficient", True))
    ):
        return "non_openai_sources_available"
    return None


def log_openai_source_skip(
    role: str,
    config: dict[str, Any] | None,
    *,
    openai_available: bool,
    non_openai_available: bool,
    point_in_time_mode: bool = False,
) -> None:
    reason = openai_source_skip_reason(
        config,
        openai_available=openai_available,
        non_openai_available=non_openai_available,
        point_in_time_mode=point_in_time_mode,
    )
    if reason:
        print(
            "openai_source_skipped "
            f"role={role} reason={reason} policy={openai_sources_policy(config)}"
        )

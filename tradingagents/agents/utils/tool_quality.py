"""Tool quality, retry, and fallback helpers for agent tools."""

from __future__ import annotations

import re

import tradingagents.dataflows.interface as interface
from tradingagents.dataflows.data_quality import prepend_quality_header

TOOL_MIN_OUTPUT_CHARS = {
    "get_stock_news_openai": 500,
    "get_global_news_openai": 500,
    "get_fundamentals_openai": 350,
    "get_alpha_vantage_fundamentals": 700,
    "get_macro_analysis": 280,
    "get_sellthenews_stock_news": 320,
    "get_sellthenews_social_sentiment": 320,
    "get_sellthenews_macro_news": 360,
    "get_sellthenews_options_data": 320,
}

DEFAULT_SEMANTIC_RETRY_DISABLED_TOOLS = {
    "get_global_news_openai",
    "get_macro_news_openai",
}

INTERACTIVE_FOLLOWUP_PATTERNS = (
    "would you like",
    "if you'd like",
    "if you would like",
    "if you want, i can",
    "if you want i can",
    "do you want me to",
    "i can do this, but i need",
    "should i",
    "want me to",
    "i can fetch",
    "which follow-up",
    "which follow up",
)

VALID_SHORT_OUTPUT_PATTERNS = (
    "no earnings data found",
    "not found for",
    "no data available",
    "fallback used because openai",
    "fallback used because tool timeout",
)


def _is_trailing_interactive_followup(text: str) -> bool:
    if not text:
        return False
    tail = (
        text.strip()
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )[-700:]
    return _has_interactive_followup(tail)


def _has_interactive_followup(text: str, *, trailing_interactive: bool = False) -> bool:
    if trailing_interactive:
        return True
    normalized = (
        str(text or "")
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = stripped.lstrip("#").strip()
        for pattern in INTERACTIVE_FOLLOWUP_PATTERNS:
            if re.match(rf"^(?:[-*]\s*)?{re.escape(pattern)}\b", stripped):
                return True
    return False


def _strip_trailing_interactive_followup(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    lines = cleaned.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()

    removed_any = False
    while lines:
        tail = (
            lines[-1]
            .strip()
            .lower()
            .replace("’", "'")
            .replace("‘", "'")
            .replace("‑", "-")
            .replace("–", "-")
            .replace("—", "-")
        )
        if any(pattern in tail for pattern in INTERACTIVE_FOLLOWUP_PATTERNS):
            removed_any = True
            lines.pop()
            while lines and lines[-1].strip().startswith(("- ", "* ")):
                lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
            continue
        break

    candidate = "\n".join(lines).strip()
    if removed_any and candidate:
        return candidate
    return cleaned


def _score_output_quality(tool_name: str, output: object) -> dict:
    text = str(output or "").strip()
    lower = (
        text.lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    flags = []
    min_chars = TOOL_MIN_OUTPUT_CHARS.get(tool_name, 0)
    trailing_interactive = _is_trailing_interactive_followup(text)

    if not text:
        flags.append("empty_output")

    if _has_interactive_followup(text, trailing_interactive=trailing_interactive):
        substantial_output = len(text) >= max(1200, min_chars * 2)
        if not (trailing_interactive and substantial_output):
            flags.append("interactive_followup")

    if lower.startswith("error:") or lower.startswith("exception:"):
        flags.append("error_prefixed_output")

    if min_chars and len(text) < min_chars:
        if not any(pattern in lower for pattern in VALID_SHORT_OUTPUT_PATTERNS):
            flags.append("undersized_output")

    suspect = any(
        flag in ("empty_output", "interactive_followup", "undersized_output")
        for flag in flags
    )
    retry_recommended = suspect and "error_prefixed_output" not in flags

    score = 1.0
    for flag in flags:
        if flag in ("empty_output", "interactive_followup"):
            score -= 0.4
        elif flag == "undersized_output":
            score -= 0.2
        elif flag == "error_prefixed_output":
            score -= 0.1
    score = max(0.0, round(score, 3))

    return {
        "score": score,
        "flags": flags,
        "is_suspect": suspect,
        "retry_recommended": retry_recommended,
        "output_chars": len(text),
        "output_preview": text[:220],
        "trailing_interactive_followup": trailing_interactive,
    }


def _merge_quality_details(
    base_quality: dict,
    data_quality: dict,
) -> dict:
    merged = dict(base_quality or {})
    existing_flags = list(merged.get("flags", []) or [])
    data_flags = list(data_quality.get("flags", []) or [])
    merged["flags"] = sorted(set(existing_flags + data_flags))
    merged["is_suspect"] = bool(
        merged.get("is_suspect", False)
        or data_quality.get("status") in {"warn", "fail"}
    )
    merged["data_quality"] = data_quality
    return merged


def _maybe_prepend_data_quality_header(
    result: object,
    data_quality: dict,
    config: dict | None = None,
) -> str:
    if not bool((config or {}).get("data_quality_header_enabled", True)):
        return str(result or "")
    return prepend_quality_header(result, data_quality)


def _semantic_retry_disabled_tools(config: dict | None = None) -> set[str]:
    config = config or {}
    configured = config.get(
        "tool_semantic_retry_disabled_tools",
        DEFAULT_SEMANTIC_RETRY_DISABLED_TOOLS,
    )
    if configured is None:
        return set()
    if isinstance(configured, str):
        return {name.strip() for name in configured.split(",") if name.strip()}
    try:
        return {str(name).strip() for name in configured if str(name).strip()}
    except TypeError:
        return set(DEFAULT_SEMANTIC_RETRY_DISABLED_TOOLS)


def _should_retry_tool_output(
    tool_name: str,
    *,
    uses_web_search: bool,
    semantic_retry_enabled: bool,
    retry_count: int,
    max_semantic_retries: int,
    quality: dict,
    config: dict | None = None,
) -> bool:
    if not (
        uses_web_search
        and semantic_retry_enabled
        and retry_count < max_semantic_retries
        and quality.get("retry_recommended", False)
    ):
        return False

    if tool_name in _semantic_retry_disabled_tools(config):
        return False

    # Avoid expensive second global-news web search when the first result
    # is already substantive, even if it ends with an interactive tail.
    if (
        tool_name == "get_global_news_openai"
        and quality.get("output_chars", 0)
        >= TOOL_MIN_OUTPUT_CHARS.get(tool_name, 0)
    ):
        return False

    return True


def _build_timeout_fallback(tool_name: str, inputs: dict, timeout_msg: str) -> str | None:
    if tool_name != "get_fundamentals_openai":
        return None
    ticker = inputs.get("ticker")
    curr_date = inputs.get("curr_date")
    if not ticker or not curr_date:
        return None
    try:
        return interface.build_openai_fundamentals_fallback(
            ticker=str(ticker),
            curr_date=str(curr_date),
            reason=f"tool timeout before OpenAI fundamentals completed ({timeout_msg})",
        )
    except Exception:
        return None

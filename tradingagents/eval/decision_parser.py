from __future__ import annotations

import re

from .models import DecisionRecordV1


_ACTIONS = ("BUY", "HOLD", "SELL", "LONG", "NEUTRAL", "SHORT")
_FIELD_PATTERNS = {
    "confidence": r"(?:\*\*)?Confidence(?:\*\*)?\s*:\s*(.+)",
    "advisory_rating": r"(?:\*\*)?Advisory Rating(?:\*\*)?\s*:\s*(.+)",
    "thesis": r"(?:\*\*)?Thesis(?:\*\*)?\s*:\s*(.+)",
    "invalidation": r"(?:\*\*)?(?:Stop / Invalidation|Invalidation)(?:\*\*)?\s*:\s*(.+)",
    "risk_budget": r"(?:\*\*)?Risk Budget(?:\*\*)?\s*:\s*(.+)",
    "position_plan": r"(?:\*\*)?Position Plan(?:\*\*)?\s*:\s*(.+)",
}


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    cleaned = cleaned.strip("*` ")
    return cleaned or None


def _extract_field(text: str, field_name: str) -> str | None:
    pattern = _FIELD_PATTERNS[field_name]
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return _clean_field(match.group(1))


def _infer_mode(action: str | None, requested_mode: str | None) -> str | None:
    if requested_mode:
        return requested_mode
    if action in {"LONG", "NEUTRAL", "SHORT"}:
        return "trading"
    if action in {"BUY", "HOLD", "SELL"}:
        return "investment"
    return None


def _extract_action(text: str, trading_mode: str | None) -> str | None:
    if trading_mode in {"investment", "trading"}:
        action = _extract_recommendation(text, trading_mode)
        if action:
            return action

    for mode in ("investment", "trading"):
        action = _extract_recommendation(text, mode)
        if action:
            return action

    final_match = re.search(
        r"FINAL\s+(?:TRANSACTION\s+PROPOSAL|INVESTMENT\s+DECISION|TRADING\s+DECISION|DECISION)"
        r"\s*:\s*\**\s*(BUY|HOLD|SELL|LONG|NEUTRAL|SHORT)\s*\**",
        text,
        flags=re.IGNORECASE,
    )
    if final_match:
        return final_match.group(1).upper()

    for label in ("Action", "Recommendation"):
        match = re.search(
            rf"(?:\*\*)?{label}(?:\*\*)?\s*:\s*\**\s*({'|'.join(_ACTIONS)})\s*\**",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).upper()

    tail = text.upper()[-160:]
    for action in _ACTIONS:
        if re.search(rf"\b{action}\b", tail):
            return action
    return None


def _extract_recommendation(response_content: str, trading_mode: str) -> str | None:
    content = response_content.upper()
    actions = ("BUY", "HOLD", "SELL") if trading_mode == "investment" else ("LONG", "NEUTRAL", "SHORT")
    labels = (
        "FINAL TRANSACTION PROPOSAL",
        "FINAL INVESTMENT DECISION",
        "FINAL TRADING DECISION",
        "FINAL RISK MANAGEMENT DECISION",
        "FINAL DECISION",
    )
    for label in labels:
        for action in actions:
            if f"{label}: **{action}**" in content:
                return action
    for action in actions:
        if f"**{action}**" in content[-100:]:
            return action
    return None


def parse_decision_text(
    raw_text: str,
    *,
    run_id: str,
    stage: str,
    agent_name: str,
    trading_mode: str | None = None,
    horizon: str | None = None,
) -> DecisionRecordV1:
    """Parse a decision with deterministic regexes only."""
    text = raw_text or ""
    warnings: list[str] = []
    action = _extract_action(text, trading_mode)
    if not action:
        warnings.append("action_not_found")

    confidence = _extract_field(text, "confidence")
    if not confidence:
        warnings.append("confidence_not_found")

    parsed_mode = _infer_mode(action, trading_mode)
    parser_status = "ok" if action else "partial"

    return DecisionRecordV1(
        run_id=run_id,
        stage=stage,
        agent_name=agent_name,
        action=action,
        confidence=confidence,
        advisory_rating=_extract_field(text, "advisory_rating"),
        trading_mode=parsed_mode,
        horizon=horizon,
        thesis=_extract_field(text, "thesis"),
        invalidation=_extract_field(text, "invalidation"),
        risk_budget=_extract_field(text, "risk_budget"),
        position_plan=_extract_field(text, "position_plan"),
        raw_text=text,
        parser_status=parser_status,
        parser_warnings=warnings,
    )

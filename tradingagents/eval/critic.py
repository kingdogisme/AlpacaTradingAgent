from __future__ import annotations

from typing import Any, Protocol

from .models import CriticRecordV1, MemoryItemRecordV1


DEFAULT_CRITIC_VERSION = "v1_diagnostic_tags"


class CriticModel(Protocol):
    def critique(self, episode: dict[str, Any]) -> CriticRecordV1:
        ...


class HeuristicCritic:
    """Deterministic critic used when no LLM critic is supplied."""

    def __init__(self, critic_version: str = DEFAULT_CRITIC_VERSION):
        self.critic_version = critic_version

    def critique(self, episode: dict[str, Any]) -> CriticRecordV1:
        reward = _latest_resolved_reward(episode)
        action = _final_action(episode)
        oracle = reward.get("oracle_label")
        reward_scalar = reward.get("reward_scalar")
        alpha = reward.get("alpha_return")
        failure_tags: list[str] = []
        final_decision = _final_decision_text(episode)
        decision_actions = _stage_actions(episode)

        if action and oracle and action != oracle:
            failure_tags.append("wrong_direction")
        if action in {"HOLD", "NEUTRAL"} and oracle in {"BUY", "LONG", "SELL", "SHORT"}:
            failure_tags.append("missed_directional_move")
            failure_tags.append("over_conservative_hold")
            if _has_future_buy_condition(final_decision):
                failure_tags.append("missed_confirmed_entry")
        if action in {"BUY", "LONG", "SELL", "SHORT"} and oracle in {"HOLD", "NEUTRAL"}:
            failure_tags.append("overtraded_neutral_market")
        if action in {"HOLD", "NEUTRAL"} and decision_actions.get("trader") in {"BUY", "LONG"}:
            failure_tags.append("risk_manager_veto")
            if oracle in {"BUY", "LONG"}:
                failure_tags.append("soft_gate_over_veto")
        if _looks_like_moving_trigger(final_decision):
            failure_tags.append("moving_trigger")
        if _has_trigger_review_context(episode) and action in {"HOLD", "NEUTRAL"}:
            failure_tags.append("trigger_met_but_no_action")
        if reward_scalar is not None and float(reward_scalar) < 0:
            failure_tags.append("negative_reward")
        if alpha is not None and float(alpha) < 0:
            failure_tags.append("underperformed_benchmark")

        if not failure_tags:
            failure_tags.append("no_failure_detected")

        evidence_spans = [
            span["span_id"]
            for span in episode.get("trace_spans", [])
            if span.get("span_type") in {"final_decision", "agent_output", "tool_call"}
        ][:8]
        reflection = _reflection_text(action, oracle, reward)
        candidates = _improvement_candidates(failure_tags)
        return CriticRecordV1(
            run_id=episode["run_id"],
            critic_version=self.critic_version,
            failure_tags=failure_tags,
            evidence_spans=evidence_spans,
            reward_snapshot=reward,
            reflection_text=reflection,
            improvement_candidates=candidates,
            parser_status="heuristic",
        )


def critic_memory_candidate(record: CriticRecordV1) -> MemoryItemRecordV1:
    return MemoryItemRecordV1(
        memory_item_id=f"critic:{record.run_id}:{record.critic_version}",
        memory_type="semantic_candidate",
        content=record.reflection_text,
        source="critic",
        status="candidate",
        evidence_json={
            "run_id": record.run_id,
            "critic_run_id": record.run_id,
            "critic_version": record.critic_version,
            "failure_tags": record.failure_tags,
        },
        metadata_json={"improvement_candidates": record.improvement_candidates},
        created_at=record.created_at,
    )


def _latest_resolved_reward(episode: dict[str, Any]) -> dict[str, Any]:
    resolved = [
        reward
        for reward in episode.get("rewards", [])
        if reward.get("reward_status", "resolved") == "resolved"
    ]
    if not resolved:
        return {}
    return resolved[-1]


def _final_action(episode: dict[str, Any]) -> str | None:
    for decision in episode.get("decisions", []):
        if decision.get("stage") == "final":
            return decision.get("action")
    return episode.get("final_signal")


def _final_decision_text(episode: dict[str, Any]) -> str:
    for decision in episode.get("decisions", []):
        if decision.get("stage") == "final":
            return str(decision.get("raw_text") or "")
    return ""


def _stage_actions(episode: dict[str, Any]) -> dict[str, str | None]:
    return {str(decision.get("stage")): decision.get("action") for decision in episode.get("decisions", [])}


def _reflection_text(action: str | None, oracle: str | None, reward: dict[str, Any]) -> str:
    if action and oracle and action != oracle:
        return (
            f"Final action {action} disagreed with outcome label {oracle}. "
            "Review the final synthesis, benchmark regime, and invalidation logic before promoting this pattern."
        )
    if reward.get("reward_scalar") is not None and float(reward["reward_scalar"]) < 0:
        return (
            "The final decision produced negative reward despite matching available structure. "
            "Review timing, transaction-cost sensitivity, and risk posture."
        )
    return "No deterministic failure was detected for this resolved episode."


def _improvement_candidates(failure_tags: list[str]) -> list[str]:
    candidates: list[str] = []
    if "wrong_direction" in failure_tags:
        candidates.append("Compare final risk-manager override against trader and research-manager actions.")
    if "missed_directional_move" in failure_tags:
        candidates.append("Inspect whether neutral decision thresholds were too conservative for this horizon.")
    if "over_conservative_hold" in failure_tags:
        candidates.append("Review whether soft gates should have reduced starter size instead of vetoing a confirmed entry.")
    if "moving_trigger" in failure_tags:
        candidates.append("Compare the new entry trigger against the active prior conditional plan before changing thresholds.")
    if "trigger_met_but_no_action" in failure_tags:
        candidates.append("Force trigger review to choose execute, resize, cancel, or supersede with explicit reason.")
    if "overtraded_neutral_market" in failure_tags:
        candidates.append("Tighten neutral-band checks before directional recommendations.")
    if "underperformed_benchmark" in failure_tags:
        candidates.append("Add benchmark-regime evidence to final synthesis.")
    if not candidates:
        candidates.append("No change candidate from deterministic critic.")
    return candidates


def _has_future_buy_condition(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("breakout", "pullback", "retest", "confirmation", "trigger", "突破", "回踩", "确认"))


def _looks_like_moving_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("new trigger", "stricter", "supersede", "retest", "新的", "更严格", "重新等待"))


def _has_trigger_review_context(episode: dict[str, Any]) -> bool:
    metadata = episode.get("metadata") if isinstance(episode.get("metadata"), dict) else {}
    review = metadata.get("active_plan_review") if isinstance(metadata.get("active_plan_review"), dict) else {}
    reviews = review.get("reviews") if isinstance(review.get("reviews"), list) else []
    return any(item.get("status") in {"met", "partially_met"} for item in reviews if isinstance(item, dict))

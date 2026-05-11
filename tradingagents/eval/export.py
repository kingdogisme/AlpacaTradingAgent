from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .ledger import EpisodeLedger


def export_jsonl(
    ledger: EpisodeLedger,
    *,
    since: str | None = None,
    output_path: Path | None = None,
    include_high_leakage: bool = False,
) -> int:
    rows = _export_records(ledger, since=since, include_high_leakage=include_high_leakage)
    line_count = 0
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
                line_count += 1
    else:
        for row in rows:
            print(json.dumps(row, sort_keys=True, ensure_ascii=False))
            line_count += 1
    return line_count


def _export_records(
    ledger: EpisodeLedger,
    *,
    since: str | None,
    include_high_leakage: bool,
) -> Iterable[dict[str, Any]]:
    episodes = ledger.list_episodes({"since": since} if since else {})
    for episode_record in episodes:
        episode = ledger.load_episode(episode_record.run_id)
        if not episode:
            continue
        leakage = (episode.get("metadata") or {}).get("data_leakage_risk", "unknown")
        if leakage == "high" and not include_high_leakage:
            continue
        base = {
            "run_id": episode["run_id"],
            "symbol": episode["symbol"],
            "trade_date": episode["trade_date"],
        }
        yield {
            **base,
            "record_type": "episode",
            "status": episode["status"],
            "final_signal": episode.get("final_signal"),
            "audit_path": episode.get("audit_path"),
            "metadata": episode.get("metadata") or {},
            "experiment": episode.get("experiment") or {},
        }
        for decision in episode.get("decisions", []):
            yield {**base, "record_type": "decision", **decision, "raw_text": _redacted_text_ref(decision)}
        for reward in episode.get("rewards", []):
            yield {**base, "record_type": "reward", **reward}
        for span in episode.get("trace_spans", []):
            yield {**base, "record_type": "trace_span", **span}
        for critic in episode.get("critic_records", []):
            yield {**base, "record_type": "critic", **critic}
        for memory in ledger.list_memory_items(run_id=episode["run_id"]):
            yield {**base, "record_type": "memory_item", **memory}


def _redacted_text_ref(decision: dict[str, Any]) -> str:
    text = decision.get("raw_text") or ""
    return f"<redacted:{len(str(text))}_chars>"

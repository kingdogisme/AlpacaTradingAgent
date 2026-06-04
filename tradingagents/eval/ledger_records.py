"""Serialization helpers for EpisodeLedger records."""

from __future__ import annotations

import json
from typing import Any


def json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, ensure_ascii=False)


def json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback

from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Iterable


_ISO_DATE_RE = re.compile(r"\b(20\d{2}|19\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b")
_MONTH_DATE_RE = re.compile(
    r"\b("
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    r")\s+([0-3]?\d),\s*((?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m"):
        try:
            parsed = datetime.strptime(text[:10] if "%d" in fmt else text[:7], fmt)
            return parsed.date()
        except ValueError:
            pass
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def extract_dates(text: str) -> list[date]:
    raw = str(text or "")
    found: list[date] = []
    for match in _ISO_DATE_RE.finditer(raw):
        parsed = parse_date(match.group(0).replace("/", "-"))
        if parsed:
            found.append(parsed)
    for match in _MONTH_DATE_RE.finditer(raw):
        parsed = parse_date(match.group(0))
        if parsed:
            found.append(parsed)
    return found


def freshest_date(values: Iterable[object]) -> date | None:
    parsed = [item for item in (parse_date(value) for value in values) if item is not None]
    return max(parsed) if parsed else None


def freshest_date_in_text(text: str) -> date | None:
    dates = extract_dates(text)
    return max(dates) if dates else None


def is_fresh_date(
    source_date: date | None,
    *,
    as_of: date | str | datetime | None = None,
    max_age_days: int,
    future_tolerance_days: int = 1,
) -> bool:
    if source_date is None:
        return False
    as_of_date = parse_date(as_of) or datetime.now(timezone.utc).date()
    age_days = (as_of_date - source_date).days
    return -future_tolerance_days <= age_days <= max_age_days


def date_age_days(source_date: date | None, *, as_of: date | str | datetime | None = None) -> int | None:
    if source_date is None:
        return None
    as_of_date = parse_date(as_of) or datetime.now(timezone.utc).date()
    return (as_of_date - source_date).days

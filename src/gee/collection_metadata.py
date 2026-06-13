from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def collection_scene_dates(collection: Any, limit: int = 20) -> list[str]:
    try:
        timestamps = collection.aggregate_array("system:time_start").sort().getInfo()
    except Exception:
        return []
    dates: list[str] = []
    for timestamp in timestamps[:limit]:
        try:
            dates.append(datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC).date().isoformat())
        except Exception:
            continue
    return sorted(set(dates))


def dates_metadata(source: str, dates: list[str], details: str = "") -> dict[str, Any]:
    return {
        "source": source,
        "dates": dates,
        "details": details,
    }

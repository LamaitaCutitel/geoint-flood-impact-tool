from __future__ import annotations

import os
from urllib.parse import quote

from src.impact_tool.external.models import ExternalResult


MAPTILER_BUILDINGS_URL = (
    "https://api.maptiler.com/maps/streets-v2/{{z}}/{{x}}/{{y}}.png?key={api_key}"
)


def county_buildings_context(api_key: str | None = None) -> ExternalResult:
    key = api_key if api_key is not None else os.getenv("MAPTILER_API_KEY", "")
    if not key:
        return ExternalResult.failure(
            source="MapTiler",
            warning="Cheia MapTiler lipsește; contextul clădirilor este ascuns.",
        )
    return ExternalResult.success(
        {"tile_url": MAPTILER_BUILDINGS_URL.format(api_key=quote(key, safe=""))},
        source="MapTiler",
        duration_seconds=0.0,
    )

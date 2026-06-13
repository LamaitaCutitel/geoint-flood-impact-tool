from __future__ import annotations

import os
from urllib.parse import quote

from src.impact_tool.external.models import ExternalResult


MAPTILER_STREETS_URL = (
    "https://api.maptiler.com/maps/streets-v2/{{z}}/{{x}}/{{y}}.png?key={api_key}"
)


def county_maptiler_context(api_key: str | None = None) -> ExternalResult:
    key = api_key if api_key is not None else os.getenv("MAPTILER_API_KEY", "")
    if not key:
        return ExternalResult.failure(
            source="MapTiler",
            warning="Cheia MapTiler lipsește; contextul cartografic opțional este ascuns.",
        )
    return ExternalResult.success(
        {"tile_url": MAPTILER_STREETS_URL.format(api_key=quote(key, safe=""))},
        source="Context cartografic MapTiler Streets",
        duration_seconds=0.0,
    )

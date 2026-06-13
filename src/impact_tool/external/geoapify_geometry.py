from __future__ import annotations

import os
from time import perf_counter
from typing import Any

import requests

from src.impact_tool.external.http import build_session, request_json, romanian_http_error
from src.impact_tool.external.models import ExternalResult


GEOMETRY_ENDPOINT = "https://api.geoapify.com/v1/geometry"


def geometry_operation(
    operation: str,
    geometry: dict[str, Any],
    *,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> ExternalResult:
    key = api_key if api_key is not None else os.getenv("GEOAPIFY_API_KEY", "")
    if not key:
        return ExternalResult.failure(
            source="Geoapify Geometry",
            warning="Cheia Geoapify lipsește; geometria va fi procesată local, dacă este posibil.",
        )
    started = perf_counter()
    client = session or build_session()
    try:
        payload = request_json(
            client,
            "POST",
            GEOMETRY_ENDPOINT,
            params={"apiKey": key},
            json={"operation": operation, "geometry": geometry},
        )
        return ExternalResult.success(
            payload,
            source="Geoapify Geometry",
            duration_seconds=perf_counter() - started,
        )
    except Exception as error:
        return ExternalResult.failure(
            source="Geoapify Geometry",
            warning=romanian_http_error("Geoapify Geometry", error),
            duration_seconds=perf_counter() - started,
        )

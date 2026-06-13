from __future__ import annotations

import os
from time import perf_counter
from typing import Any

import requests
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from src.impact_tool.external.http import build_session, request_json, romanian_http_error
from src.impact_tool.external.models import ExternalResult


GEOMETRY_ENDPOINT = "https://api.geoapify.com/v1/geometry/operation"


def simplify_geometry(
    geometry: dict[str, Any],
    tolerance: float,
    *,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> ExternalResult:
    result = _typed_operation(
        {
            "operation": "simplify",
            "geometry": geometry,
            "params": {"tolerance": tolerance, "highQuality": True},
        },
        api_key=api_key,
        session=session,
    )
    if result.status.ok:
        return result
    local = mapping(shape(geometry).simplify(tolerance, preserve_topology=True))
    return ExternalResult.success(
        local,
        source="Shapely local fallback",
        duration_seconds=result.status.duration_seconds,
        completeness="complet",
        warning=result.status.warning,
    )


def buffer_geometry(
    geometry: dict[str, Any],
    distance_meters: float,
    *,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> ExternalResult:
    result = _typed_operation(
        {
            "operation": "buffer",
            "geometry": geometry,
            "distance": distance_meters,
            "params": {"units": "meters", "steps": 32},
        },
        api_key=api_key,
        session=session,
    )
    if result.status.ok:
        return result
    forward = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    reverse = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    projected = transform(forward.transform, shape(geometry))
    local = mapping(transform(reverse.transform, projected.buffer(distance_meters)))
    return ExternalResult.success(
        local,
        source="Shapely local fallback",
        duration_seconds=result.status.duration_seconds,
        completeness="complet",
        warning=result.status.warning,
    )


def _typed_operation(
    payload: dict[str, Any],
    *,
    api_key: str | None,
    session: requests.Session | None,
) -> ExternalResult:
    key = api_key if api_key is not None else os.getenv("GEOAPIFY_API_KEY", "")
    if not key:
        return ExternalResult.failure(
            source="Geoapify Geometry",
            warning="Cheia Geoapify lipsește; se folosește procesarea locală.",
        )
    started = perf_counter()
    try:
        response = request_json(
            session or build_session(),
            "POST",
            GEOMETRY_ENDPOINT,
            params={"apiKey": key},
            json=payload,
        )
        return ExternalResult.success(
            response.get("data", response),
            source="Geoapify Geometry",
            duration_seconds=perf_counter() - started,
        )
    except Exception as error:
        return ExternalResult.failure(
            source="Geoapify Geometry",
            warning=romanian_http_error("Geoapify Geometry", error),
            duration_seconds=perf_counter() - started,
        )

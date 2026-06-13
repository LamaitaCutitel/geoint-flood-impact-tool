from __future__ import annotations

import os
from time import perf_counter
from typing import Any

import requests

from src.impact_tool.external.http import build_session, request_json, romanian_http_error
from src.impact_tool.external.models import ExternalResult


PLACES_ENDPOINT = "https://api.geoapify.com/v2/places"

CATEGORY_PRIORITY = {
    "healthcare.hospital": "hospital",
    "healthcare.clinic_or_praxis": "clinic",
    "healthcare.doctor": "doctors",
    "healthcare.pharmacy": "pharmacy",
    "service.fire_station": "fire_station",
    "service.police": "police",
    "education.school": "school",
    "education.kindergarten": "kindergarten",
    "commercial.gas": "fuel",
    "service.social_facility.shelter": "shelter",
    "healthcare.ambulance_station": "ambulance_station",
    "public_transport.train": "railway_station",
    "power.substation": "power_substation",
    "power.plant": "power_plant",
    "production.water": "water_tower",
    "production.wastewater": "wastewater_plant",
}


def normalize_category(raw_categories: list[str] | None) -> str:
    categories = raw_categories or []
    for prefix, normalized in CATEGORY_PRIORITY.items():
        if any(value == prefix or value.startswith(f"{prefix}.") for value in categories):
            return normalized
    return "fallback"


def normalize_places(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        source_id = str(
            properties.get("place_id")
            or properties.get("osm_id")
            or feature.get("id")
            or ""
        )
        if not source_id or source_id in seen_ids:
            continue
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, list):
            continue
        seen_ids.add(source_id)
        raw_categories = list(properties.get("categories") or [])
        normalized.append(
            {
                "type": "Feature",
                "id": source_id,
                "geometry": {"type": "Point", "coordinates": coordinates[:2]},
                "properties": {
                    "source_id": source_id,
                    "name": properties.get("name") or properties.get("formatted") or "Fără nume",
                    "category": normalize_category(raw_categories),
                    "raw_categories": raw_categories,
                    "address": properties.get("formatted") or properties.get("address_line2") or "",
                    "coordinates": coordinates[:2],
                    "source": "Geoapify Places",
                },
            }
        )
    return {"type": "FeatureCollection", "features": normalized}


def fetch_places(
    *,
    categories: list[str],
    filter_value: str,
    api_key: str | None = None,
    session: requests.Session | None = None,
    limit: int = 500,
) -> ExternalResult:
    key = api_key if api_key is not None else os.getenv("GEOAPIFY_API_KEY", "")
    if not key:
        return ExternalResult.failure(
            source="Geoapify Places",
            warning="Cheia Geoapify lipsește; se poate folosi fallback-ul Overpass țintit.",
        )
    started = perf_counter()
    client = session or build_session()
    try:
        payload = request_json(
            client,
            "GET",
            PLACES_ENDPOINT,
            params={
                "categories": ",".join(categories),
                "filter": filter_value,
                "limit": min(max(limit, 1), 1000),
                "apiKey": key,
            },
        )
        normalized = normalize_places(payload)
        warning = ""
        completeness = "complet"
        if payload.get("features") and not normalized["features"]:
            warning = "Răspunsul Geoapify nu a conținut puncte utilizabile."
            completeness = "posibil incomplet"
        return ExternalResult.success(
            normalized,
            source="Geoapify Places",
            duration_seconds=perf_counter() - started,
            completeness=completeness,
            warning=warning,
        )
    except Exception as error:
        return ExternalResult.failure(
            source="Geoapify Places",
            warning=romanian_http_error("Geoapify Places", error),
            duration_seconds=perf_counter() - started,
        )


def fetch_important_facilities(
    *,
    filter_value: str,
    api_key: str | None = None,
    session: requests.Session | None = None,
    fallback: Any = None,
) -> ExternalResult:
    categories = list(CATEGORY_PRIORITY)
    result = fetch_places(
        categories=categories,
        filter_value=filter_value,
        api_key=api_key,
        session=session,
    )
    if result.status.ok or fallback is None:
        return result
    fallback_result = fallback()
    if fallback_result.status.ok:
        return ExternalResult.success(
            fallback_result.data,
            source=fallback_result.status.source,
            duration_seconds=(
                result.status.duration_seconds
                + fallback_result.status.duration_seconds
            ),
            completeness="posibil incomplet",
            warning=(
                f"{result.status.warning} "
                "Au fost încărcate doar obiectivele critice disponibile prin fallback."
            ),
        )
    return result

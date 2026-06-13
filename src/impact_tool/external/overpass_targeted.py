from __future__ import annotations

import os
from time import perf_counter
from typing import Any, Callable

import requests
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union

from src.impact_tool.external.http import build_session, request_json, romanian_http_error
from src.impact_tool.external.models import ExternalResult


DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
CATEGORY_LIMITS = {
    "buildings": 4000,
    "roads": 2500,
    "railways": 1000,
    "bridges": 1000,
}
HARD_ELEMENT_CAP = 12000
MIN_COMPONENT_AREA_M2 = 1000


def configured_endpoints() -> list[str]:
    primary = os.getenv("OVERPASS_ENDPOINT", DEFAULT_ENDPOINT).strip()
    fallbacks = [
        value.strip()
        for value in os.getenv("OVERPASS_FALLBACK_ENDPOINTS", "").split(",")
        if value.strip()
    ]
    return list(dict.fromkeys([primary, *fallbacks]))


def run_targeted_query(
    query: str,
    *,
    session: requests.Session | None = None,
    endpoints: list[str] | None = None,
) -> ExternalResult:
    started = perf_counter()
    client = session or build_session()
    warnings: list[str] = []
    for endpoint in endpoints or configured_endpoints():
        try:
            payload = request_json(client, "POST", endpoint, data={"data": query})
            return ExternalResult.success(
                payload,
                source=f"Overpass API ({endpoint})",
                duration_seconds=perf_counter() - started,
                completeness="posibil incomplet" if warnings else "complet",
                warning=" ".join(warnings),
            )
        except Exception as error:
            warnings.append(romanian_http_error("Overpass API", error))
    return ExternalResult.failure(
        source="Overpass API",
        warning=" ".join(warnings) or "Overpass API nu a furnizat date.",
        duration_seconds=perf_counter() - started,
        data={"elements": []},
        completeness="indisponibil",
    )


def targeted_bboxes(
    water_geometry: dict[str, Any],
    buffer_meters: int,
    *,
    max_tiles: int = 4,
) -> list[list[float]]:
    return targeted_query_plan(
        water_geometry,
        buffer_meters,
        max_tiles=max_tiles,
    )["boxes"]


def targeted_query_plan(
    water_geometry: dict[str, Any],
    buffer_meters: int,
    *,
    max_tiles: int = 4,
) -> dict[str, Any]:
    if not water_geometry:
        raise ValueError("Geometria apei SAR este obligatorie pentru interogarea OSM.")
    if not 1 <= buffer_meters <= 1000:
        raise ValueError("Bufferul trebuie să fie între 1 și 1000 m.")
    forward = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    reverse = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    water = transform(forward.transform, shape(water_geometry))
    if not water.is_valid:
        water = water.buffer(0)
    water = water.simplify(10, preserve_topology=True)
    components = list(water.geoms) if hasattr(water, "geoms") else [water]
    significant = [
        component
        for component in components
        if not component.is_empty and component.area >= MIN_COMPONENT_AREA_M2
    ]
    if not significant:
        significant = [water]
    significant.sort(key=lambda geometry: geometry.area, reverse=True)
    buffered = [component.buffer(buffer_meters) for component in significant]
    merged_boxes = unary_union([box(*geometry.bounds) for geometry in buffered])
    merged = list(merged_boxes.geoms) if hasattr(merged_boxes, "geoms") else [merged_boxes]
    merged.sort(key=lambda geometry: geometry.area, reverse=True)
    selected = merged[: max(1, max_tiles)]
    geographic = [transform(reverse.transform, geometry) for geometry in selected]
    boxes = [[*geometry.bounds] for geometry in geographic]
    return {
        "boxes": boxes,
        "component_count": len(components),
        "query_box_count": len(boxes),
        "covered_area_km2": round(sum(item.area for item in selected) / 1_000_000, 3),
        "discarded_small_components": len(components) - len(significant),
    }


def build_targeted_query(category: str, bbox: list[float], limit: int) -> str:
    if category not in CATEGORY_LIMITS:
        raise ValueError(f"Categorie OSM neacceptată: {category}")
    west, south, east, north = bbox
    area = f"{south},{west},{north},{east}"
    selectors = {
        "buildings": f'nwr["building"]({area});',
        "roads": (
            'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
            f'residential|service|unclassified|.*_link)$"]({area});'
        ),
        "railways": f'way["railway"]({area});',
        "bridges": (
            f'nwr["bridge"]({area});'
            f'way["man_made"="bridge"]({area});'
        ),
    }
    return (
        "[out:json][timeout:25];"
        f"({selectors[category]});"
        f"out body {limit};>;out skel qt;"
    )


def deduplicate_elements(
    elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    unique: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for element in elements:
        stable_id = f"{element.get('type', '')}:{element.get('id', '')}"
        if stable_id in unique:
            duplicates += 1
        unique[stable_id] = element
    return list(unique.values()), duplicates


def fetch_targeted_impact(
    *,
    water_geometry: dict[str, Any],
    buffer_meters: int,
    categories: tuple[str, ...] = ("buildings", "roads", "railways", "bridges"),
    fetcher: Callable[[str], ExternalResult] = run_targeted_query,
    hard_cap: int = HARD_ELEMENT_CAP,
    max_tiles: int = 4,
) -> ExternalResult:
    started = perf_counter()
    plan = targeted_query_plan(water_geometry, buffer_meters, max_tiles=max_tiles)
    boxes = plan["boxes"]
    category_data: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    duplicate_count = 0
    truncated = False
    total = 0
    category_status: dict[str, dict[str, Any]] = {}
    for category in categories:
        collected: list[dict[str, Any]] = []
        per_tile_limit = max(1, CATEGORY_LIMITS[category] // len(boxes))
        for bbox in boxes:
            result = fetcher(build_targeted_query(category, bbox, per_tile_limit))
            if not result.status.ok:
                errors.append(f"{category}: {result.status.warning}")
                continue
            collected.extend((result.data or {}).get("elements", []))
        deduplicated, duplicates = deduplicate_elements(collected)
        duplicate_count += duplicates
        remaining = max(0, hard_cap - total)
        if len(deduplicated) > remaining:
            deduplicated = deduplicated[:remaining]
            truncated = True
        category_data[category] = deduplicated
        category_errors = [
            error for error in errors if error.startswith(f"{category}:")
        ]
        category_status[category] = {
            "ok": not category_errors,
            "raw_elements": len(collected),
            "deduplicated_elements": len(deduplicated),
            "truncated": len(deduplicated) >= remaining and len(collected) > remaining,
            "warnings": category_errors,
        }
        total += len(deduplicated)
        if total >= hard_cap:
            truncated = True
            break
    warning_parts = errors[:]
    if truncated:
        warning_parts.append(
            "Limita de siguranță OSM a fost atinsă; afișarea este trunchiată."
        )
    completeness = "complet"
    if errors or truncated:
        completeness = "posibil incomplet"
    return ExternalResult.success(
        {
            "categories": category_data,
            "metadata": {
                "tile_count": len(boxes),
                "duplicates_removed": duplicate_count,
                "errors": errors,
                "truncated": truncated,
                "element_count": total,
                "query_scope": "SAR new water + warning buffer",
                "category_status": category_status,
                **{key: value for key, value in plan.items() if key != "boxes"},
            },
        },
        source="Overpass API țintit",
        duration_seconds=perf_counter() - started,
        completeness=completeness,
        warning=" ".join(warning_parts),
    )

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from shapely.geometry import LineString, mapping, shape
from shapely.ops import polygonize, unary_union

from src.app_support.osm_impact import (
    OVERPASS_FALLBACK_URLS,
    USER_AGENT,
    _node_feature,
    _way_feature,
    _with_exposure,
    build_osm_geojson_layers,
    build_overpass_query,
)
from src.impact_tool.cache import PersistentCache


OSM_CATEGORIES = ("buildings", "roads", "railways", "bridges", "critical")
OSM_LIMITS = {
    "buildings": 50000,
    "roads": 25000,
    "railways": 10000,
    "bridges": 10000,
    "critical": 15000,
}
OVERPASS_TIMEOUT_SECONDS = 60
OVERPASS_HTTP_TIMEOUT_SECONDS = 85
OSM_QUERY_VERSION = "4"
OSM_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
OSM_MAX_TILE_DEPTH = 2
ROAD_LINK_CLASSES = {
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}
LAYER_BY_CATEGORY = {
    "buildings": "osm_buildings",
    "roads": "osm_roads",
    "railways": "osm_railways",
    "bridges": "osm_bridges",
    "critical": "osm_critical",
}
OSM_ATTRIBUTION = "© OpenStreetMap contributors"


def fetch_overpass(query: str) -> dict[str, Any]:
    payload = urlencode({"data": query}).encode("utf-8")
    last_error: Exception | None = None
    for endpoint in OVERPASS_FALLBACK_URLS:
        try:
            request = Request(endpoint, data=payload, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=OVERPASS_HTTP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return {"elements": []}


def load_osm_categories(
    *,
    analysis_complete: bool,
    aoi_hash: str,
    bbox: list[float],
    geometry: dict[str, Any],
    cache: PersistentCache,
    categories: tuple[str, ...] = OSM_CATEGORIES,
    fetcher: Callable[[str], dict[str, Any]] = fetch_overpass,
    ttl_seconds: int = OSM_CACHE_TTL_SECONDS,
    analysis_mode: str = "detaliat",
) -> dict[str, Any]:
    if not analysis_complete:
        raise RuntimeError("Datele OSM pot fi încărcate numai după analiza SAR.")
    layers: dict[str, dict[str, Any]] = {}
    cache_refs: dict[str, str] = {}
    status: dict[str, dict[str, Any]] = {}
    geometry_hash = osm_geometry_hash(geometry)
    for category in categories:
        category_started = perf_counter()
        try:
            fetched = _load_category_tiles(
                bbox=bbox,
                category=category,
                cache=cache,
                fetcher=fetcher,
                ttl_seconds=ttl_seconds,
                analysis_mode=analysis_mode,
            )
            elements = fetched["elements"]
            parsed = build_osm_geojson_layers(elements)
            _append_link_road_features(parsed, elements)
            _append_relation_features(parsed, elements)
            if category == "critical":
                relation_features = parsed["osm_critical"].get("features", [])
                parsed["osm_critical"] = _critical_layer(elements)
                parsed["osm_critical"]["features"].extend(relation_features)
            _deduplicate_layer_features(parsed)
            filtered = filter_osm_layers_to_geometry(parsed, geometry)
            layer_id = LAYER_BY_CATEGORY[category]
            layers[layer_id] = filtered[layer_id]
            layer_cache_key = cache.key(
                "osm-layers",
                geometry_hash,
                category,
                _query_version(analysis_mode, category),
            )
            cache.set("osm-layers", layer_cache_key, layers[layer_id])
            cache_refs[layer_id] = layer_cache_key
            status[category] = {
                "ok": True,
                "count": len(layers[layer_id].get("features", [])),
                "source": fetched["source"],
                "cache_date": fetched["cache_date"],
                "completeness": fetched["completeness"],
                "warnings": fetched["warnings"],
                "tile_count": fetched["tile_count"],
                "duplicate_count": fetched["duplicate_count"],
                "relation_count": fetched["relation_count"],
                "errors": fetched["errors"],
                "duration_seconds": round(
                    perf_counter() - category_started,
                    3,
                ),
            }
            cache.set(
                "osm-metadata",
                _metadata_key(cache, geometry_hash, category, analysis_mode),
                {
                    **status[category],
                    "geometry_hash": geometry_hash,
                    "category": category,
                    "query_version": _query_version(analysis_mode, category),
                    "limit": OSM_LIMITS[category],
                    "tile_keys": fetched["tile_keys"],
                },
            )
        except Exception as exc:
            status[category] = {
                "ok": False,
                "count": None,
                "error": str(exc),
                "source": "indisponibil",
                "completeness": "indisponibil",
                "duration_seconds": round(
                    perf_counter() - category_started,
                    3,
                ),
            }
    return {
        "layers": layers,
        "status": status,
        "cache_refs": cache_refs,
        "attribution": OSM_ATTRIBUTION,
    }


def retry_osm_category(**kwargs: Any) -> dict[str, Any]:
    category = kwargs.pop("category")
    return load_osm_categories(categories=(category,), **kwargs)


def build_category_query(
    bbox: list[float],
    category: str,
    limit: int | None = None,
    analysis_mode: str = "detaliat",
) -> str:
    limit = limit or OSM_LIMITS[category]
    west, south, east, north = bbox
    area = f"{south},{west},{north},{east}"
    if category == "buildings":
        return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}][maxsize:536870912];
(
  way["building"]({area});
  relation["building"]({area});
);
out body {limit};
>;
out skel qt;
"""
    if category == "roads":
        road_classes = (
            "motorway|motorway_link|trunk|trunk_link|primary|primary_link|"
            "secondary|secondary_link|tertiary|tertiary_link|residential|"
            "service|unclassified"
        )
        return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}][maxsize:536870912];
(
  way["highway"~"^({road_classes})$"]({area});
);
out body {limit};
>;
out skel qt;
"""
    if category != "critical":
        return re.sub(
            r"\[timeout:\d+\]",
            f"[timeout:{OVERPASS_TIMEOUT_SECONDS}]",
            build_overpass_query(bbox, limit, category=category),
        )
    power_classes = (
        "substation|plant|generator|transformer"
        if analysis_mode == "rapid"
        else "substation|plant|generator|transformer|pole|tower|line|cable"
    )
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}][maxsize:536870912];
(
  nwr["amenity"~"^(hospital|clinic|pharmacy|fire_station|police|school|kindergarten|fuel)$"]({area});
  nwr["healthcare"]({area});
  nwr["emergency"]({area});
  nwr["power"~"^({power_classes})$"]({area});
);
out body {limit};
>;
out skel qt;
"""


def split_bbox(bbox: list[float]) -> list[list[float]]:
    west, south, east, north = bbox
    middle_x = (west + east) / 2
    middle_y = (south + north) / 2
    return [
        [west, south, middle_x, middle_y],
        [middle_x, south, east, middle_y],
        [west, middle_y, middle_x, north],
        [middle_x, middle_y, east, north],
    ]


def deduplicate_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, Any], dict[str, Any]] = {}
    for element in elements:
        key = (str(element.get("type", "")), element.get("id"))
        unique[key] = element
    return list(unique.values())


def load_cached_osm_layers(
    cache: PersistentCache,
    cache_refs: dict[str, str],
) -> dict[str, dict[str, Any]]:
    layers: dict[str, dict[str, Any]] = {}
    for layer_id, key in cache_refs.items():
        cached = cache.get("osm-layers", key)
        if cached.hit and isinstance(cached.value, dict):
            layers[layer_id] = cached.value
    return layers


def _deduplicate_layer_features(
    layers: dict[str, dict[str, Any]],
) -> None:
    for layer in layers.values():
        features = layer.get("features", [])
        relation_members = {
            member_id
            for feature in features
            if feature.get("properties", {}).get("osm_type") == "relation"
            for member_id in feature.get("properties", {}).get("member_way_ids", [])
        }
        unique: dict[tuple[str, Any], dict[str, Any]] = {}
        anonymous: list[dict[str, Any]] = []
        for feature in features:
            properties = feature.get("properties", {})
            osm_type = properties.get("osm_type")
            osm_id = properties.get("osm_id")
            if osm_type == "way" and osm_id in relation_members:
                continue
            if osm_type and osm_id is not None:
                unique[(str(osm_type), osm_id)] = feature
            else:
                anonymous.append(feature)
        layer["features"] = list(unique.values()) + anonymous


def osm_geometry_hash(geometry: Any) -> str:
    payload = json.dumps(
        geometry,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _query_version(analysis_mode: str, category: str = "") -> str:
    if category == "critical":
        return f"{OSM_QUERY_VERSION}-{analysis_mode}"
    return OSM_QUERY_VERSION


def _metadata_key(
    cache: PersistentCache,
    geometry_hash: str,
    category: str,
    analysis_mode: str = "detaliat",
) -> str:
    return cache.key(
        "osm-metadata",
        geometry_hash,
        category,
        _query_version(analysis_mode, category),
        OSM_LIMITS[category],
    )


def inspect_osm_cache(
    cache: PersistentCache,
    geometry: dict[str, Any],
    categories: tuple[str, ...] = OSM_CATEGORIES,
    ttl_seconds: int = OSM_CACHE_TTL_SECONDS,
    analysis_mode: str = "detaliat",
) -> dict[str, dict[str, Any]]:
    geometry_hash = osm_geometry_hash(geometry)
    result: dict[str, dict[str, Any]] = {}
    for category in categories:
        metadata = cache.get(
            "osm-metadata",
            _metadata_key(cache, geometry_hash, category, analysis_mode),
            ttl_seconds=ttl_seconds,
        )
        if metadata.expired:
            result[category] = {"status": "expirat"}
            continue
        if not metadata.hit or not isinstance(metadata.value, dict):
            result[category] = {"status": "lipsă"}
            continue
        value = metadata.value
        tile_results = [
            cache.get("osm", key, ttl_seconds=ttl_seconds)
            for key in value.get("tile_keys", [])
        ]
        if any(tile.expired for tile in tile_results):
            result[category] = {**value, "status": "expirat"}
        elif not tile_results or any(not tile.hit for tile in tile_results):
            result[category] = {**value, "status": "lipsă"}
        elif value.get("completeness") != "complet":
            result[category] = {**value, "status": "incomplet"}
        else:
            result[category] = {**value, "status": "valid"}
    return result


def filter_osm_layers_to_geometry(
    layers: dict[str, dict[str, Any]],
    geometry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    active_area = shape(geometry)
    filtered: dict[str, dict[str, Any]] = {}
    for layer_id, layer in layers.items():
        features = []
        for feature in layer.get("features", []):
            try:
                if shape(feature.get("geometry") or {}).intersects(active_area):
                    features.append(feature)
            except (TypeError, ValueError):
                continue
        filtered[layer_id] = {**layer, "features": features}
    return filtered


def _append_link_road_features(
    layers: dict[str, dict[str, Any]],
    elements: list[dict[str, Any]],
) -> None:
    nodes = {
        element["id"]: (float(element["lon"]), float(element["lat"]))
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    existing = {
        (
            feature.get("properties", {}).get("osm_type"),
            feature.get("properties", {}).get("osm_id"),
        )
        for feature in layers["osm_roads"].get("features", [])
    }
    for element in elements:
        tags = element.get("tags") or {}
        if (
            element.get("type") != "way"
            or tags.get("highway") not in ROAD_LINK_CLASSES
            or ("way", element.get("id")) in existing
        ):
            continue
        feature = _way_feature(element, nodes)
        if feature:
            layers["osm_roads"]["features"].append(
                _with_exposure(feature, "medium", "drum potențial afectat")
            )


def _load_category_tiles(
    *,
    bbox: list[float],
    category: str,
    cache: PersistentCache,
    fetcher: Callable[[str], dict[str, Any]],
    ttl_seconds: int,
    analysis_mode: str,
) -> dict[str, Any]:
    limit = OSM_LIMITS[category]
    warnings: list[str] = []
    sources: set[str] = set()
    cache_dates: list[str] = []
    tile_keys: list[str] = []
    tile_count = 0

    def fetch_tile(tile_bbox: list[float], depth: int = 0) -> tuple[list[dict[str, Any]], bool]:
        nonlocal tile_count
        tile_count += 1
        tile_hash = osm_geometry_hash({"bbox": [round(value, 8) for value in tile_bbox]})
        key = cache.key(
            "osm",
            tile_hash,
            category,
            _query_version(analysis_mode, category),
            limit,
        )
        tile_keys.append(key)
        cached = cache.get("osm", key, ttl_seconds=ttl_seconds)
        if cached.hit:
            value = cached.value or {}
            if isinstance(value, list):
                elements = value
                cached_at = ""
            else:
                elements = value.get("elements", [])
                cached_at = value.get("fetched_at", "")
            sources.add("cache")
            cache_dates.append(cached_at)
        else:
            payload = fetcher(
                build_category_query(
                    tile_bbox,
                    category,
                    limit,
                    analysis_mode=analysis_mode,
                )
            )
            elements = payload.get("elements", [])
            cached_at = datetime.now(timezone.utc).isoformat()
            cache.set(
                "osm",
                key,
                {"elements": elements, "fetched_at": cached_at, "bbox": tile_bbox},
            )
            sources.add("Overpass API")
            cache_dates.append(cached_at)

        limit_reached = _primary_element_count(elements, category) >= limit
        if limit_reached and depth < OSM_MAX_TILE_DEPTH:
            tiled_elements: list[dict[str, Any]] = []
            complete = True
            for child_bbox in split_bbox(tile_bbox):
                child_elements, child_complete = fetch_tile(child_bbox, depth + 1)
                tiled_elements.extend(child_elements)
                complete = complete and child_complete
            return tiled_elements, complete
        if limit_reached:
            warnings.append(
                f"Categoria {category} a atins limita de {limit} elemente "
                f"la adâncimea maximă {OSM_MAX_TILE_DEPTH}."
            )
            return elements, False
        return elements, True

    elements, complete = fetch_tile(bbox)
    deduplicated = deduplicate_elements(elements)
    return {
        "elements": deduplicated,
        "source": "cache" if sources == {"cache"} else "Overpass API",
        "cache_date": max(cache_dates) if cache_dates else "",
        "completeness": "complet" if complete else "posibil incomplet",
        "warnings": warnings,
        "tile_count": tile_count,
        "duplicate_count": len(elements) - len(deduplicated),
        "relation_count": sum(
            1 for element in deduplicated if element.get("type") == "relation"
        ),
        "errors": [],
        "tile_keys": list(dict.fromkeys(tile_keys)),
    }


def _primary_element_count(
    elements: list[dict[str, Any]],
    category: str,
) -> int:
    count = 0
    for element in elements:
        tags = element.get("tags") or {}
        if category == "buildings" and tags.get("building"):
            count += 1
        elif category == "roads" and tags.get("highway"):
            count += 1
        elif category == "railways" and tags.get("railway"):
            count += 1
        elif category == "bridges" and tags.get("bridge"):
            count += 1
        elif category == "critical" and (
            tags.get("amenity")
            or tags.get("healthcare")
            or tags.get("emergency")
            or tags.get("power")
        ):
            count += 1
    return count


def _critical_layer(elements: list[dict[str, Any]]) -> dict[str, Any]:
    critical_amenities = {
        "hospital",
        "clinic",
        "pharmacy",
        "fire_station",
        "police",
        "school",
        "kindergarten",
        "fuel",
    }
    nodes = {
        element["id"]: (float(element["lon"]), float(element["lat"]))
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    collection = {
        "type": "FeatureCollection",
        "display_name": "Obiective critice potențial expuse OSM",
        "color": "#dc2626",
        "features": [],
    }
    for element in elements:
        tags = element.get("tags") or {}
        relevant = (
            tags.get("amenity") in critical_amenities
            or bool(tags.get("healthcare"))
            or bool(tags.get("emergency"))
            or bool(tags.get("power"))
        )
        if not relevant:
            continue
        feature = (
            _node_feature(element)
            if element.get("type") == "node"
            else _way_feature(element, nodes)
            if element.get("type") == "way"
            else None
        )
        if not feature:
            continue
        properties = feature.setdefault("properties", {})
        properties["power"] = tags.get("power")
        collection["features"].append(
            _with_exposure(feature, "high", "obiectiv critic potențial expus")
        )
    return collection


def _append_relation_features(
    layers: dict[str, dict[str, Any]],
    elements: list[dict[str, Any]],
) -> None:
    nodes = {
        element["id"]: (float(element["lon"]), float(element["lat"]))
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    ways = {
        element["id"]: [
            nodes[node_id] for node_id in element.get("nodes", []) if node_id in nodes
        ]
        for element in elements
        if element.get("type") == "way"
    }
    for relation in elements:
        tags = relation.get("tags") or {}
        if relation.get("type") != "relation" or tags.get("type") != "multipolygon":
            continue
        outer_lines = []
        inner_lines = []
        for member in relation.get("members", []):
            coordinates = ways.get(member.get("ref"), [])
            if len(coordinates) < 2:
                continue
            target = inner_lines if member.get("role") == "inner" else outer_lines
            target.append(LineString(coordinates))
        outer = unary_union(list(polygonize(outer_lines)))
        if outer.is_empty:
            continue
        inner = unary_union(list(polygonize(inner_lines)))
        geometry = outer.difference(inner) if not inner.is_empty else outer
        feature = {
            "type": "Feature",
            "geometry": mapping(geometry),
            "properties": {
                **tags,
                "tags": tags,
                "osm_type": "relation",
                "osm_id": relation.get("id"),
                "member_way_ids": [
                    member.get("ref")
                    for member in relation.get("members", [])
                    if member.get("type") == "way"
                ],
            },
        }
        if tags.get("building"):
            layers["osm_buildings"]["features"].append(
                _with_exposure(feature, "high", "cladire potential afectata")
            )
        if (
            tags.get("amenity")
            or tags.get("healthcare")
            or tags.get("emergency")
            or tags.get("power")
        ):
            layers["osm_critical"]["features"].append(
                _with_exposure(
                    feature,
                    "high",
                    "obiectiv critic potențial expus",
                )
            )

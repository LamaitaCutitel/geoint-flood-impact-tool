from __future__ import annotations

import json
from functools import lru_cache
from math import atan2, cos, radians, sin, sqrt
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK_URLS = (
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
)
USER_AGENT = "geoint-flood-impact-dashboard/1.0"
CRITICAL_AMENITIES = {"hospital", "clinic", "doctors", "fire_station", "police", "school"}
ROAD_TAGS = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "service", "unclassified"}
OSM_QUERY_CATEGORIES = ("buildings", "roads", "critical", "railways", "bridges")


def expanded_bbox(bbox: list[float], buffer_meters: int) -> list[float]:
    west, south, east, north = [float(value) for value in bbox]
    delta_lat = buffer_meters / 111_320
    center_lat = (south + north) / 2
    delta_lon = buffer_meters / max(1, 111_320 * cos(radians(center_lat)))
    return [west - delta_lon, south - delta_lat, east + delta_lon, north + delta_lat]


def build_overpass_query(bbox: list[float], limit: int = 5000, category: str | None = None) -> str:
    west, south, east, north = bbox
    area = f"{south},{west},{north},{east}"
    body = "\n".join(_category_query_lines(area, category))
    return f"""
[out:json][timeout:18][maxsize:536870912];
(
{body}
);
out body {limit};
>;
out skel qt;
"""


def _category_query_lines(area: str, category: str | None) -> list[str]:
    categories = OSM_QUERY_CATEGORIES if category is None else (category,)
    lines: list[str] = []
    if "buildings" in categories:
        lines.append(f'  way["building"]({area});')
    if "roads" in categories:
        lines.append(f'  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|service|unclassified)$"]({area});')
    if "critical" in categories:
        amenities = "|".join(sorted(CRITICAL_AMENITIES))
        lines.append(f'  node["amenity"~"^({amenities})$"]({area});')
        lines.append(f'  way["amenity"~"^({amenities})$"]({area});')
    if "railways" in categories:
        lines.append(f'  way["railway"~"^(rail|tram|light_rail|subway)$"]({area});')
    if "bridges" in categories:
        lines.append(f'  way["bridge"]({area});')
        lines.append(f'  node["bridge"]({area});')
    return lines


def fetch_osm_operational_impact(
    bbox: list[float],
    buffer_meters: int = 500,
    limit: int = 5000,
    fetcher: Any | None = None,
    county_geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return fetch_osm_operational_impact_payload(
        bbox,
        buffer_meters=buffer_meters,
        limit=limit,
        fetcher=fetcher,
        county_geometry=county_geometry,
    )["metrics"]


def fetch_osm_operational_impact_payload(
    bbox: list[float],
    buffer_meters: int = 500,
    limit: int = 5000,
    fetcher: Any | None = None,
    county_geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query_bbox = expanded_bbox(bbox, buffer_meters)
    if fetcher is not None:
        query = build_overpass_query(query_bbox, limit)
        data = fetcher(query)
        elements = data.get("elements", [])
        query_errors: list[str] = []
    else:
        elements, query_errors = _fetch_overpass_by_category(query_bbox, limit)
    layers = build_osm_geojson_layers(elements)
    if county_geometry:
        layers = filter_osm_layers_to_geometry(layers, county_geometry)
    metrics = summarize_osm_layers(layers, buffer_meters, limit, len(elements))
    metrics["osm_query_errors"] = query_errors
    return {
        "metrics": metrics,
        "layers": layers,
    }


@lru_cache(maxsize=16)
def _cached_overpass(query: str) -> dict[str, Any]:
    payload = urlencode({"data": query}).encode("utf-8")
    last_error: Exception | None = None
    for endpoint in OVERPASS_FALLBACK_URLS:
        try:
            request = Request(endpoint, data=payload, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return {"elements": []}


def _fetch_overpass_by_category(bbox: list[float], limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    elements_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    errors: list[str] = []
    effective_limit = max(50, min(int(limit), 500))
    for category in OSM_QUERY_CATEGORIES:
        query = build_overpass_query(bbox, effective_limit, category=category)
        try:
            data = _cached_overpass(query)
        except Exception as exc:
            errors.append(f"{category}: {exc}")
            continue
        for element in data.get("elements", []):
            if "id" in element and "type" in element:
                elements_by_key[(str(element["type"]), int(element["id"]))] = element
    return list(elements_by_key.values()), errors


def summarize_osm_elements(elements: list[dict[str, Any]], buffer_meters: int, limit: int) -> dict[str, Any]:
    nodes = {
        element["id"]: (float(element["lat"]), float(element["lon"]))
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    buildings = 0
    road_km = 0.0
    rail_km = 0.0
    critical = 0
    bridges = 0

    for element in elements:
        tags = element.get("tags") or {}
        element_type = element.get("type")
        if "building" in tags and element_type in {"way", "relation"}:
            buildings += 1
        amenity = tags.get("amenity")
        if amenity in CRITICAL_AMENITIES:
            critical += 1
        if "bridge" in tags:
            bridges += 1
        if element_type != "way":
            continue
        length_km = _way_length_km(element.get("nodes") or [], nodes)
        if tags.get("highway") in ROAD_TAGS:
            road_km += length_km
        if tags.get("railway") and tags.get("railway") != "abandoned":
            rail_km += length_km

    return {
        "osm_buildings_potentially_affected": buildings,
        "osm_roads_intersected_km": round(road_km, 3),
        "osm_critical_assets": critical,
        "osm_railways_intersected_km": round(rail_km, 3),
        "osm_bridges": bridges,
        "osm_query_buffer_m": buffer_meters,
        "osm_query_limit": limit,
        "osm_elements_returned": len(elements),
    }


def build_osm_geojson_layers(elements: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    nodes = {
        element["id"]: (float(element["lon"]), float(element["lat"]))
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    layers = {
        "osm_buildings": _feature_collection("Cladiri potential afectate OSM", "#ef4444"),
        "osm_roads": _feature_collection("Drumuri potential afectate OSM", "#f97316"),
        "osm_critical": _feature_collection("Obiective critice potential expuse OSM", "#7c3aed"),
        "osm_railways": _feature_collection("Cai ferate intersectate OSM", "#111827"),
        "osm_bridges": _feature_collection("Poduri intersectate OSM", "#0ea5e9"),
    }
    for element in elements:
        tags = element.get("tags") or {}
        if element.get("type") == "node":
            feature = _node_feature(element)
        elif element.get("type") == "way":
            feature = _way_feature(element, nodes)
        else:
            feature = None
        if not feature:
            continue
        if "building" in tags:
            layers["osm_buildings"]["features"].append(
                _with_exposure(feature, "high", "cladire potential afectata")
            )
        if tags.get("highway") in ROAD_TAGS:
            layers["osm_roads"]["features"].append(
                _with_exposure(feature, "medium", "drum potential afectat")
            )
        if tags.get("railway") and tags.get("railway") != "abandoned":
            layers["osm_railways"]["features"].append(
                _with_exposure(feature, "medium", "cale ferata intersectata")
            )
        if tags.get("amenity") in CRITICAL_AMENITIES:
            layers["osm_critical"]["features"].append(
                _with_exposure(feature, "high", "obiectiv critic potential expus")
            )
        if "bridge" in tags:
            layers["osm_bridges"]["features"].append(
                _with_exposure(feature, "high", "pod intersectat")
            )
    return layers


def filter_osm_layers_to_geometry(
    layers: dict[str, dict[str, Any]],
    county_geometry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    filtered: dict[str, dict[str, Any]] = {}
    for layer_id, layer in layers.items():
        kept_features = [
            feature
            for feature in layer.get("features", [])
            if _feature_intersects_geometry(feature.get("geometry") or {}, county_geometry)
        ]
        filtered[layer_id] = {**layer, "features": kept_features}
    return filtered


def summarize_osm_layers(
    layers: dict[str, dict[str, Any]],
    buffer_meters: int,
    limit: int,
    raw_elements_returned: int | None = None,
) -> dict[str, Any]:
    roads_km = sum(_feature_length_km(feature) for feature in layers.get("osm_roads", {}).get("features", []))
    rail_km = sum(_feature_length_km(feature) for feature in layers.get("osm_railways", {}).get("features", []))
    return {
        "osm_buildings_potentially_affected": len(layers.get("osm_buildings", {}).get("features", [])),
        "osm_roads_intersected_km": round(roads_km, 3),
        "osm_critical_assets": len(layers.get("osm_critical", {}).get("features", [])),
        "osm_railways_intersected_km": round(rail_km, 3),
        "osm_bridges": len(layers.get("osm_bridges", {}).get("features", [])),
        "osm_query_buffer_m": buffer_meters,
        "osm_query_limit": limit,
        "osm_elements_returned": raw_elements_returned if raw_elements_returned is not None else sum(
            len(layer.get("features", [])) for layer in layers.values()
        ),
    }


def _feature_collection(display_name: str, color: str) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "display_name": display_name,
        "color": color,
        "features": [],
    }


def _node_feature(element: dict[str, Any]) -> dict[str, Any] | None:
    if "lat" not in element or "lon" not in element:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(element["lon"]), float(element["lat"])]},
        "properties": _properties(element),
    }


def _way_feature(element: dict[str, Any], nodes: dict[int, tuple[float, float]]) -> dict[str, Any] | None:
    coordinates = [nodes[node_id] for node_id in element.get("nodes", []) if node_id in nodes]
    if len(coordinates) < 2:
        return None
    is_polygon = len(coordinates) >= 4 and coordinates[0] == coordinates[-1] and "building" in (element.get("tags") or {})
    geometry = {
        "type": "Polygon" if is_polygon else "LineString",
        "coordinates": [coordinates] if is_polygon else coordinates,
    }
    return {"type": "Feature", "geometry": geometry, "properties": _properties(element)}


def _properties(element: dict[str, Any]) -> dict[str, Any]:
    tags = element.get("tags") or {}
    return {
        "osm_id": element.get("id"),
        "name": tags.get("name", "fara nume"),
        "osm_type": element.get("type"),
        "amenity": tags.get("amenity"),
        "highway": tags.get("highway"),
        "railway": tags.get("railway"),
        "building": tags.get("building"),
        "bridge": tags.get("bridge"),
        "operator": tags.get("operator"),
        "addr_city": tags.get("addr:city"),
        "addr_street": tags.get("addr:street"),
        "addr_housenumber": tags.get("addr:housenumber"),
        "emergency": tags.get("emergency"),
        "healthcare": tags.get("healthcare"),
    }


def _with_exposure(feature: dict[str, Any], level: str, label: str) -> dict[str, Any]:
    properties = dict(feature.get("properties") or {})
    properties["exposure_level"] = level
    properties["exposure_label"] = label
    properties["osm_source"] = "OpenStreetMap"
    properties["distance_to_extent"] = "nedisponibila"
    properties["exposure_status"] = "intersected" if "intersectat" in label else "within buffer"
    return {**feature, "properties": properties}


def _way_length_km(node_ids: list[int], nodes: dict[int, tuple[float, float]]) -> float:
    total = 0.0
    for previous_id, current_id in zip(node_ids, node_ids[1:]):
        if previous_id in nodes and current_id in nodes:
            total += _haversine_km(nodes[previous_id], nodes[current_id])
    return total


def _feature_length_km(feature: dict[str, Any]) -> float:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "LineString":
        return _coordinate_line_length_km(coordinates)
    if geometry.get("type") == "Polygon":
        return _coordinate_line_length_km(coordinates[0] if coordinates else [])
    return 0.0


def _coordinate_line_length_km(coordinates: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(coordinates, coordinates[1:]):
        if len(start) >= 2 and len(end) >= 2:
            total += _haversine_km((float(start[1]), float(start[0])), (float(end[1]), float(end[0])))
    return total


def _feature_intersects_geometry(feature_geometry: dict[str, Any], county_geometry: dict[str, Any]) -> bool:
    points = _geometry_points(feature_geometry)
    if not points:
        return False
    polygons = _county_polygons(county_geometry)
    return any(_point_in_polygon(point, polygon) for point in points for polygon in polygons)


def _geometry_points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Point" and len(coordinates) >= 2:
        return [(float(coordinates[0]), float(coordinates[1]))]
    if geometry_type == "LineString":
        return [(float(lon), float(lat)) for lon, lat, *_ in coordinates]
    if geometry_type == "Polygon":
        ring = coordinates[0] if coordinates else []
        points = [(float(lon), float(lat)) for lon, lat, *_ in ring]
        centroid = _centroid(points)
        return points + ([centroid] if centroid else [])
    return []


def _county_polygons(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return [[(float(lon), float(lat)) for lon, lat, *_ in coordinates[0]]]
    if geometry_type == "MultiPolygon":
        return [[(float(lon), float(lat)) for lon, lat, *_ in polygon[0]] for polygon in coordinates if polygon]
    return []


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not points:
        return None
    return (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    if len(polygon) < 3:
        return False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        if _point_on_segment(point, (previous_x, previous_y), (current_x, current_y)):
            return True
        intersects = (current_y > y) != (previous_y > y)
        if intersects:
            x_intersection = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x <= x_intersection:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    tolerance: float = 1e-10,
) -> bool:
    x, y = point
    x1, y1 = start
    x2, y2 = end
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > tolerance:
        return False
    return min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance and min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance


def _haversine_km(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1 = start
    lat2, lon2 = end
    radius_km = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return radius_km * 2 * atan2(sqrt(a), sqrt(1 - a))

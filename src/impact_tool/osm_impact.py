from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform
from shapely.prepared import prep
from shapely.strtree import STRtree


STATUS_DIRECT = "Intersectat direct"
STATUS_BUFFER = "În buffer de avertizare"
STATUS_UNEXPOSED = "Neexpus"
STATUS_REFERENCE = "Referință"
STATUS_CONTEXT = "Context"
REFERENCE_BUILDING_LIMIT = 750
PROJECTED_CACHE_LIMIT = 4
_PROJECTED_LAYER_CACHE: OrderedDict[str, dict[str, dict[str, Any]]] = OrderedDict()

SYMBOLS = {
    "hospital": "✚",
    "clinic": "✚",
    "pharmacy": "+",
    "fire_station": "♨",
    "police": "◆",
    "school": "▣",
    "kindergarten": "▣",
    "fuel": "⛽",
    "power": "⚡",
    "bridge": "⌒",
    "station": "◆",
    "fallback": "●",
}


def _transformers() -> tuple[Transformer, Transformer]:
    return (
        Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True),
        Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True),
    )


def buffered_geometry(
    geometry: dict[str, Any],
    buffer_meters: int,
) -> tuple[dict[str, Any], list[float]]:
    forward, reverse = _transformers()
    projected = transform(forward.transform, shape(geometry))
    expanded = transform(reverse.transform, projected.buffer(buffer_meters))
    west, south, east, north = expanded.bounds
    return mapping(expanded), [west, south, east, north]


def classify_osm_impact(
    layers: dict[str, dict[str, Any]],
    water_geometry: dict[str, Any],
    buffer_meters: int,
    active_geometry: dict[str, Any] | None = None,
    projection_cache_key: str = "",
) -> dict[str, Any]:
    if not 1 <= buffer_meters <= 1000:
        raise ValueError("Bufferul trebuie să fie între 1 și 1000 m.")
    forward, reverse = _transformers()
    project = lambda geometry: transform(forward.transform, geometry)
    unproject = lambda geometry: transform(reverse.transform, geometry)
    water = project(shape(water_geometry))
    warning_area = water.buffer(buffer_meters)
    reference_area = water.buffer(500)
    buffer_only = warning_area.difference(water)
    active_area = project(shape(active_geometry)) if active_geometry else None
    water_prepared = prep(water)
    warning_prepared = prep(warning_area)
    reference_prepared = prep(reference_area)
    active_prepared = prep(active_area) if active_area is not None else None
    classified: dict[str, dict[str, Any]] = {}
    status_counts: Counter[str] = Counter()
    metrics = {
        "buildings_direct": 0,
        "buildings_buffer": 0,
        "buildings_area_m2": 0.0,
        "buildings_overlap_m2": 0.0,
        "buildings_complete": 0,
        "buildings_partial": 0,
        "roads_direct_km": 0.0,
        "roads_buffer_km": 0.0,
        "railways_direct_km": 0.0,
        "railways_buffer_km": 0.0,
        "bridges_direct": 0,
        "bridges_buffer": 0,
        "critical_direct": 0,
        "critical_buffer": 0,
        "road_classes": {},
    }
    prepared_layers = _prepare_projected_layers(
        layers,
        project,
        projection_cache_key,
        unproject(water.buffer(1000)) if projection_cache_key else None,
    )
    for layer_id, collection in layers.items():
        features = []
        prepared = prepared_layers[layer_id]
        source_features = prepared["features"]
        projected_geometries = prepared["geometries"]
        spatial_index = prepared["tree"]
        direct_candidates = _query_indices(
            spatial_index,
            projected_geometries,
            water,
        )
        warning_candidates = _query_indices(
            spatial_index,
            projected_geometries,
            warning_area,
        )
        candidate_indices = set(range(len(source_features)))
        if projection_cache_key:
            candidate_indices = set(warning_candidates)
            if layer_id == "osm_buildings":
                candidate_indices.update(
                    _query_indices(
                        spatial_index,
                        projected_geometries,
                        reference_area,
                    )
                )
        for index in sorted(candidate_indices):
            feature = source_features[index]
            projected = projected_geometries[index]
            if index in direct_candidates and water_prepared.intersects(projected):
                status = STATUS_DIRECT
            elif index in warning_candidates and warning_prepared.intersects(projected):
                status = STATUS_BUFFER
            elif layer_id == "osm_buildings" and reference_prepared.intersects(projected):
                status = STATUS_REFERENCE
            else:
                status = STATUS_UNEXPOSED
            properties = dict(feature.get("properties") or {})
            properties["status"] = status
            properties["distance_to_water_m"] = round(projected.distance(water), 1)
            properties["symbol"] = symbol_for_feature(properties, layer_id)
            properties["outside_active_area"] = bool(
                active_prepared is not None
                and not active_prepared.intersects(projected)
            )
            properties["infrastructure_level"] = infrastructure_level(
                properties,
                layer_id,
            )
            direct_geometry = (
                projected.intersection(water)
                if status == STATUS_DIRECT
                else None
            )
            buffer_geometry = (
                projected.intersection(buffer_only)
                if status in {STATUS_DIRECT, STATUS_BUFFER}
                and layer_id in {"osm_roads", "osm_railways"}
                else None
            )
            clipped = (
                projected.intersection(warning_area)
                if status in {STATUS_DIRECT, STATUS_BUFFER}
                and layer_id in {"osm_roads", "osm_railways", "osm_bridges"}
                else direct_geometry
            )
            context_geometry = (
                projected.difference(warning_area)
                if status in {STATUS_DIRECT, STATUS_BUFFER}
                and layer_id in {"osm_roads", "osm_railways"}
                else None
            )
            features.append(
                {
                    **feature,
                    "properties": properties,
                    "original_geometry": feature["geometry"],
                    "clipped_geometry": (
                        mapping(unproject(clipped))
                        if clipped is not None and not clipped.is_empty
                        else None
                    ),
                    "direct_geometry": (
                        mapping(unproject(direct_geometry))
                        if direct_geometry is not None and not direct_geometry.is_empty
                        else None
                    ),
                    "buffer_geometry": (
                        mapping(unproject(buffer_geometry))
                        if buffer_geometry is not None and not buffer_geometry.is_empty
                        else None
                    ),
                    "context_geometry": (
                        mapping(unproject(context_geometry))
                        if context_geometry is not None and not context_geometry.is_empty
                        else None
                    ),
                }
            )
            status_counts[status] += 1
            _accumulate_metrics(
                metrics,
                layer_id,
                projected,
                water,
                buffer_only,
                status,
                properties,
                direct_geometry,
                buffer_geometry,
            )
        classified[layer_id] = {
            **collection,
            "features": features,
            "analysis_features": features,
        }
    _attach_display_features(classified, water, project)
    return {
        "layers": classified,
        "buffer_geometry": mapping(unproject(warning_area)),
        "water_geometry": water_geometry,
        "metrics": {**metrics, "status_counts": dict(status_counts)},
        "buffer_meters": buffer_meters,
    }


def _prepare_projected_layers(
    layers: dict[str, dict[str, Any]],
    project: Any,
    cache_key: str,
    candidate_area: Any | None = None,
) -> dict[str, dict[str, Any]]:
    if cache_key and cache_key in _PROJECTED_LAYER_CACHE:
        prepared = _PROJECTED_LAYER_CACHE.pop(cache_key)
        _PROJECTED_LAYER_CACHE[cache_key] = prepared
        return prepared
    prepared = {}
    candidate_prepared = prep(candidate_area) if candidate_area is not None else None
    for layer_id, collection in layers.items():
        features = []
        geometries = []
        for feature in collection.get("features", []):
            geometry = shape(feature["geometry"])
            if candidate_prepared is not None and not candidate_prepared.intersects(geometry):
                continue
            features.append(feature)
            geometries.append(project(geometry))
        prepared[layer_id] = {
            "features": features,
            "geometries": geometries,
            "tree": STRtree(geometries) if geometries else None,
        }
    if cache_key:
        _PROJECTED_LAYER_CACHE[cache_key] = prepared
        while len(_PROJECTED_LAYER_CACHE) > PROJECTED_CACHE_LIMIT:
            _PROJECTED_LAYER_CACHE.popitem(last=False)
    return prepared


def symbol_for_feature(properties: dict[str, Any], layer_id: str) -> str:
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else properties
    amenity = tags.get("amenity") or tags.get("healthcare")
    if amenity in SYMBOLS:
        return SYMBOLS[amenity]
    if layer_id == "osm_bridges":
        return SYMBOLS["bridge"]
    if tags.get("power"):
        return SYMBOLS["power"]
    if tags.get("railway") == "station":
        return SYMBOLS["station"]
    return SYMBOLS["fallback"]


def visible_impact_layers(
    impact: dict[str, Any],
    filters: dict[str, bool],
    critical_only: bool,
) -> dict[str, dict[str, Any]]:
    mapping_ids = {
        "osm_buildings": "buildings",
        "osm_roads": "roads",
        "osm_railways": "railways",
        "osm_bridges": "bridges",
        "osm_critical": "critical",
    }
    result = {}
    for layer_id, collection in impact.get("layers", {}).items():
        if not filters.get(mapping_ids[layer_id], True):
            continue
        if critical_only and layer_id not in {"osm_roads", "osm_bridges", "osm_critical"}:
            continue
        source_features = collection.get(
            "display_features",
            collection.get("features", []),
        )
        features = [
            feature
            for feature in source_features
            if feature.get("properties", {}).get("status") != STATUS_UNEXPOSED
            and (
                filters.get("reference_buildings", True)
                or feature.get("properties", {}).get("status") != STATUS_REFERENCE
            )
        ]
        result[layer_id] = {**collection, "features": features}
    return result


def _attach_display_features(
    layers: dict[str, dict[str, Any]],
    water: Any,
    project: Any,
) -> None:
    for layer_id, collection in layers.items():
        analysis_features = collection.get("analysis_features", [])
        affected = [
            feature
            for feature in analysis_features
            if feature.get("properties", {}).get("status")
            in {STATUS_DIRECT, STATUS_BUFFER}
        ]
        if layer_id != "osm_buildings":
            if layer_id in {"osm_roads", "osm_railways"}:
                collection["display_features"] = _linear_display_features(affected)
            else:
                collection["display_features"] = affected
            continue

        affected_geometries = [
            project(shape(feature["geometry"]))
            for feature in affected
        ]
        if affected_geometries:
            from shapely.ops import unary_union

            reference_area = unary_union(affected_geometries).buffer(500)
        else:
            reference_area = water.buffer(500)

        references = []
        for feature in analysis_features:
            properties = feature.get("properties", {})
            if properties.get("status") in {STATUS_DIRECT, STATUS_BUFFER}:
                continue
            projected = project(shape(feature["geometry"]))
            if not projected.intersects(reference_area):
                continue
            references.append(
                {
                    **feature,
                    "properties": {
                        **properties,
                        "status": STATUS_REFERENCE,
                        "distance_to_water_m": round(projected.distance(water), 1),
                    },
                }
            )
        references.sort(
            key=lambda feature: feature.get("properties", {}).get(
                "distance_to_water_m",
                float("inf"),
            )
        )
        collection["display_features"] = affected + references[:REFERENCE_BUILDING_LIMIT]


def _query_indices(
    tree: STRtree | None,
    geometries: list[Any],
    query_geometry: Any,
) -> set[int]:
    if tree is None:
        return set()
    matches = tree.query(query_geometry)
    if hasattr(matches, "tolist"):
        matches = matches.tolist()
    if not matches:
        return set()
    if isinstance(matches[0], int):
        return {int(index) for index in matches}
    index_by_identity = {id(geometry): index for index, geometry in enumerate(geometries)}
    return {
        index_by_identity[id(geometry)]
        for geometry in matches
        if id(geometry) in index_by_identity
    }


def _linear_display_features(
    affected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    geometry_statuses = (
        ("direct_geometry", STATUS_DIRECT),
        ("buffer_geometry", STATUS_BUFFER),
        ("context_geometry", STATUS_CONTEXT),
    )
    for feature in affected:
        for geometry_key, status in geometry_statuses:
            geometry = feature.get(geometry_key)
            if not geometry:
                continue
            result.append(
                {
                    **feature,
                    "geometry": geometry,
                    "properties": {
                        **feature.get("properties", {}),
                        "status": status,
                    },
                }
            )
    return result


def infrastructure_level(properties: dict[str, Any], layer_id: str) -> str:
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else properties
    if (
        tags.get("amenity") in {"hospital", "clinic", "fire_station", "police"}
        or tags.get("healthcare")
        or tags.get("power")
    ):
        return "esențial"
    if (
        layer_id in {"osm_bridges", "osm_railways"}
        or tags.get("highway") in {"motorway", "trunk", "primary", "secondary"}
        or tags.get("amenity") in {"pharmacy", "school", "kindergarten", "fuel"}
    ):
        return "important"
    return "context tehnic"


def _accumulate_metrics(
    metrics: dict[str, Any],
    layer_id: str,
    geometry: Any,
    water: Any,
    buffer_only: Any,
    status: str,
    properties: dict[str, Any],
    direct_geometry: Any | None = None,
    buffer_geometry: Any | None = None,
) -> None:
    suffix = "direct" if status == STATUS_DIRECT else "buffer" if status == STATUS_BUFFER else ""
    if not suffix:
        return
    if layer_id == "osm_buildings":
        metrics[f"buildings_{suffix}"] += 1
        metrics["buildings_area_m2"] += round(geometry.area, 1)
        if status == STATUS_DIRECT:
            overlap = direct_geometry.area if direct_geometry is not None else 0
            complete = geometry.within(water)
            metrics["buildings_overlap_m2"] += round(overlap, 1)
            metrics["buildings_complete" if complete else "buildings_partial"] += 1
            properties["intersection_type"] = "completă" if complete else "parțială"
    elif layer_id in {"osm_roads", "osm_railways"}:
        prefix = "roads" if layer_id == "osm_roads" else "railways"
        direct_km = (
            direct_geometry.length / 1000
            if direct_geometry is not None
            else 0
        )
        buffer_km = (
            buffer_geometry.length / 1000
            if buffer_geometry is not None
            else 0
        )
        metrics[f"{prefix}_direct_km"] += round(direct_km, 3)
        metrics[f"{prefix}_buffer_km"] += round(buffer_km, 3)
        if layer_id == "osm_roads":
            road_class = properties.get("highway") or "necunoscut"
            class_metrics = metrics["road_classes"].setdefault(
                road_class,
                {"direct_km": 0.0, "buffer_km": 0.0},
            )
            class_metrics["direct_km"] = round(class_metrics["direct_km"] + direct_km, 3)
            class_metrics["buffer_km"] = round(class_metrics["buffer_km"] + buffer_km, 3)
    elif layer_id == "osm_bridges":
        metrics[f"bridges_{suffix}"] += 1
    elif layer_id == "osm_critical":
        metrics[f"critical_{suffix}"] += 1

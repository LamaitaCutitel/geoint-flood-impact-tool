from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from shapely.geometry import shape

from src.gee.dynamic_world import (
    dynamic_world_change_map,
    dynamic_world_mode,
    dynamic_world_water_change_masks,
)
from src.gee.gee_config import COLLECTIONS
from src.gee.gee_tile_layers import ee_tile_url
from src.gee.sar_water_masks import sar_dynamic_world_overlap


TRANSITION_CLASSES = {
    4: "crops",
    2: "grass",
    6: "built",
    1: "trees",
    3: "flooded vegetation",
    5: "shrub and scrub",
    7: "bare",
}
CLASS_NAMES = {
    0: "apă",
    1: "arbori",
    2: "iarbă",
    3: "vegetație inundată",
    4: "culturi",
    5: "arbuști",
    6: "construit",
    7: "teren gol",
    8: "zăpadă/gheață",
}


def scene_day_period(scene: dict[str, Any], window_days: int = 15) -> tuple[str, str]:
    acquired = datetime.fromisoformat(str(scene["acquisition_time"]).replace("Z", "+00:00"))
    return (
        (acquired.date() - timedelta(days=window_days)).isoformat(),
        (acquired.date() + timedelta(days=window_days + 1)).isoformat(),
    )


def run_dynamic_world_analysis(
    ee: Any,
    aoi: Any,
    before_scene: dict[str, Any],
    after_scene: dict[str, Any],
    sar_new_water: Any,
    scale_meters: int = 10,
) -> dict[str, Any]:
    before_target = str(before_scene["acquisition_time"])[:10]
    after_target = str(after_scene["acquisition_time"])[:10]
    before_period = scene_day_period(before_scene)
    after_period = scene_day_period(after_scene)
    try:
        before, before_metadata = _select_observation(
            ee,
            aoi,
            before_target,
            before_period,
            scale_meters,
        )
        after, after_metadata = _select_observation(
            ee,
            aoi,
            after_target,
            after_period,
            scale_meters,
        )
    except Exception as exc:
        return {
            "status": "indisponibil",
            "error": str(exc),
            "periods": {"before": before_period, "after": after_period},
            "acquisition_dates": {"before": None, "after": None},
            "product_types": {"before": None, "after": None},
            "tiles": {},
            "metrics": {},
            "metric_values": {},
            "transitions": {},
            "transition_values": {},
        }

    change = dynamic_world_change_map(ee, before, after, aoi)
    water_masks = dynamic_world_water_change_masks(before, after, sar_new_water, aoi)
    correlation = sar_dynamic_world_overlap(
        sar_new_water,
        water_masks["dynamic_world_new_water"],
        aoi,
    )
    metric_masks = {
        "dynamic_world_new_water_area_km2": water_masks["dynamic_world_new_water"],
        "sar_dynamic_world_new_water_overlap_area_km2": correlation[
            "sar_dynamic_world_new_water_overlap"
        ],
        "new_water_only_sar_area_km2": correlation["new_water_only_sar"],
        "new_water_only_dynamic_world_area_km2": correlation[
            "new_water_only_dynamic_world"
        ],
    }
    transition_masks = {
        class_name: before.eq(class_id).And(after.eq(0)).selfMask().clip(aoi)
        for class_id, class_name in TRANSITION_CLASSES.items()
    }
    combined_statuses = _combined_metric_statuses(
        ee,
        {**metric_masks, **transition_masks},
        aoi,
        scale_meters,
    )
    metrics = {key: combined_statuses[key] for key in metric_masks}
    transitions = {key: combined_statuses[key] for key in transition_masks}
    metric_values = _successful_values(metrics)
    transition_values = _successful_values(transitions)

    tile_images = {
        "dynamic_world_before": (before, "Dynamic World before"),
        "dynamic_world_after": (after, "Dynamic World after"),
        "dynamic_world_changes": (change, "Land cover changes"),
        "dynamic_world_new_water": (
            water_masks["dynamic_world_new_water"],
            "Dynamic World - apa noua",
        ),
        "both_methods": (
            correlation["sar_dynamic_world_new_water_overlap"],
            "SAR x Dynamic World new water overlap",
        ),
        "only_sar": (correlation["new_water_only_sar"], "New water only SAR"),
        "only_dynamic_world": (
            correlation["new_water_only_dynamic_world"],
            "New water only Dynamic World",
        ),
    }
    tiles = {
        key: _tile_status(image, name)
        for key, (image, name) in tile_images.items()
    }
    mandatory_tile_ids = (
        "dynamic_world_before",
        "dynamic_world_after",
        "dynamic_world_new_water",
    )
    mandatory_tiles_ready = _mandatory_tiles_ready(tiles, mandatory_tile_ids)
    result_status = "reușit" if mandatory_tiles_ready else "tile indisponibil"
    result_error = (
        None
        if mandatory_tiles_ready
        else "Lipsesc unul sau mai multe tile-uri obligatorii Dynamic World."
    )
    overlap = metric_values.get(
        "sar_dynamic_world_new_water_overlap_area_km2",
        0.0,
    )
    only_sar = metric_values.get("new_water_only_sar_area_km2", 0.0)
    only_dynamic = metric_values.get(
        "new_water_only_dynamic_world_area_km2",
        0.0,
    )
    return {
        "status": result_status,
        "error": result_error,
        "products": {
            "before": before,
            "after": after,
            "changes": change,
            **water_masks,
            **correlation,
        },
        "periods": {"before": before_period, "after": after_period},
        "acquisition_dates": {
            "before": before_metadata["acquisition_date"],
            "after": after_metadata["acquisition_date"],
        },
        "product_types": {
            "before": before_metadata["product_type"],
            "after": after_metadata["product_type"],
        },
        "coverage": {
            "before": before_metadata["coverage"],
            "after": after_metadata["coverage"],
        },
        "metrics": metrics,
        "metric_values": metric_values,
        "transitions": transitions,
        "transition_values": transition_values,
        "tiles": tiles,
        "charts": {
            "water_areas": {
                "Apă nouă SAR": only_sar + overlap,
                "Apă nouă Dynamic World": only_dynamic + overlap,
                "Suprapunere": overlap,
            },
            "transitions": transition_values,
        },
    }


def _select_observation(
    ee: Any,
    aoi: Any,
    target_date: str,
    period: tuple[str, str],
    scale_meters: int,
) -> tuple[Any, dict[str, Any]]:
    target = ee.Date(target_date)
    collection = (
        ee.ImageCollection(COLLECTIONS.dynamic_world)
        .filterBounds(aoi)
        .filterDate(period[0], period[1])
        .select("label")
    )
    count = int(collection.size().getInfo())
    if count == 0:
        raise RuntimeError(
            f"Dynamic World nu are observații în perioada {period[0]} - {period[1]}."
        )

    total_pixels = ee.Image.constant(1).reduceRegion(
        reducer=ee.Reducer.count(),
        geometry=aoi,
        scale=scale_meters,
        maxPixels=1e9,
        bestEffort=True,
    ).values().get(0)

    def score(image: Any) -> Any:
        valid_pixels = image.select("label").mask().reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=scale_meters,
            maxPixels=1e9,
            bestEffort=True,
        ).values().get(0)
        coverage = ee.Number(valid_pixels).divide(ee.Number(total_pixels).max(1))
        distance = image.date().difference(target, "day").abs()
        selection_score = coverage.multiply(1_000_000).subtract(distance)
        return image.set(
            {
                "valid_pixels": valid_pixels,
                "aoi_coverage": coverage,
                "distance_to_target": distance,
                "selection_score": selection_score,
            }
        )

    scored = collection.map(score).sort("selection_score", False)
    selected = ee.Image(scored.first())
    coverage = float(ee.Number(selected.get("aoi_coverage")).getInfo() or 0)
    product_type = "observație individuală"
    if _needs_mosaic(coverage):
        selected = dynamic_world_mode(ee, aoi, period[0], period[1])
        product_type = "mozaic fallback"
        acquisition_date = f"{period[0]} - {period[1]}"
    else:
        acquisition_date = (
            ee.Date(selected.get("system:time_start")).format("YYYY-MM-dd").getInfo()
        )
    return selected.clip(aoi), {
        "acquisition_date": acquisition_date,
        "coverage": round(coverage, 4),
        "product_type": product_type,
        "search_period": period,
    }


def _needs_mosaic(coverage: float) -> bool:
    return float(coverage) < 0.85


def _mandatory_tiles_ready(
    tiles: dict[str, dict[str, Any]],
    mandatory_ids: tuple[str, ...],
) -> bool:
    return all(
        tiles.get(key, {}).get("status") == "reușit"
        and bool(tiles.get(key, {}).get("url"))
        for key in mandatory_ids
    )


def _metric_statuses(
    ee: Any,
    masks: dict[str, Any],
    aoi: Any,
    scale_meters: int,
) -> dict[str, dict[str, Any]]:
    result = {}
    for key, mask in masks.items():
        try:
            value = round(_strict_mask_area_km2(ee, mask, aoi, scale_meters), 4)
            result[key] = {"value": value, "status": "reușit", "error": None}
        except Exception as exc:
            result[key] = {"value": None, "status": "eroare", "error": str(exc)}
    return result


def _combined_metric_statuses(
    ee: Any,
    masks: dict[str, Any],
    aoi: Any,
    scale_meters: int,
) -> dict[str, dict[str, Any]]:
    if not masks:
        return {}
    band_names = {
        key: f"metric_{index}"
        for index, key in enumerate(masks)
    }
    try:
        bands = [
            mask.multiply(ee.Image.pixelArea()).rename(band_names[key])
            for key, mask in masks.items()
        ]
        image = ee.Image.cat(*bands)
        values = image.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=scale_meters,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo() or {}
        return {
            key: {
                "value": round(
                    float(values.get(band_name) or 0) / 1_000_000,
                    4,
                ),
                "status": "reușit",
                "error": None,
            }
            for key, band_name in band_names.items()
        }
    except Exception as exc:
        return {
            key: {"value": None, "status": "eroare", "error": str(exc)}
            for key in masks
        }


def _strict_mask_area_km2(
    ee: Any,
    mask: Any,
    aoi: Any,
    scale_meters: int,
) -> float:
    stats = mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi,
        scale=scale_meters,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()
    if not stats:
        return 0.0
    value = next(iter(stats.values()))
    if value is None:
        return 0.0
    return float(value) / 1_000_000


def _tile_status(image: Any, name: str) -> dict[str, Any]:
    try:
        url = ee_tile_url(image, name)
        if not url:
            return {
                "url": None,
                "status": "tile indisponibil",
                "error": f"URL indisponibil pentru {name}.",
            }
        return {"url": url, "status": "reușit", "error": None}
    except Exception as exc:
        return {"url": None, "status": "eroare", "error": str(exc)}


def _successful_values(items: dict[str, dict[str, Any]]) -> dict[str, float]:
    return {
        key: float(item["value"])
        for key, item in items.items()
        if item.get("status") == "reușit" and item.get("value") is not None
    }


def correlate_osm_dynamic_world(
    ee: Any,
    dynamic_result: dict[str, Any],
    osm_impact: dict[str, Any],
    scale_meters: int = 10,
    feature_limit: int = 500,
) -> dict[str, Any]:
    products = dynamic_result.get("products", {})
    before = products.get("before")
    after = products.get("after")
    if before is None or after is None:
        return {
            "status": "indisponibil",
            "error": "Produsele Dynamic World BEFORE/AFTER lipsesc.",
            "rows": [],
        }
    features = []
    metadata = {}
    for layer_id, layer in osm_impact.get("layers", {}).items():
        source = layer.get("analysis_features", layer.get("features", []))
        for index, feature in enumerate(source):
            properties = feature.get("properties", {})
            if properties.get("status") not in {
                "Intersectat direct",
                "În buffer de avertizare",
            }:
                continue
            geometry, sampling_method = _correlation_geometry(feature, layer_id)
            feature_key = f"{layer_id}:{index}"
            metadata[feature_key] = {
                "feature_key": feature_key,
                "name": properties.get("name") or feature_key,
                "status": properties.get("status"),
                "sampling_method": sampling_method,
            }
            features.append(
                ee.Feature(
                    ee.Geometry(geometry),
                    {"feature_key": feature_key},
                )
            )
            if len(features) >= feature_limit:
                break
        if len(features) >= feature_limit:
            break
    if not features:
        return {"status": "reușit", "error": None, "rows": []}
    try:
        collection = ee.FeatureCollection(features)
        before_info = before.reduceRegions(
            collection=collection,
            reducer=ee.Reducer.mode(),
            scale=scale_meters,
        ).getInfo()
        after_info = after.reduceRegions(
            collection=collection,
            reducer=ee.Reducer.mode(),
            scale=scale_meters,
        ).getInfo()
        before_labels = _sample_labels(before_info)
        after_labels = _sample_labels(after_info)
        rows = []
        for feature_key, item in metadata.items():
            before_class = CLASS_NAMES.get(before_labels.get(feature_key), "indisponibil")
            after_class = CLASS_NAMES.get(after_labels.get(feature_key), "indisponibil")
            rows.append(
                {
                    **item,
                    "before_class": before_class,
                    "after_class": after_class,
                    "transition": f"{before_class} → {after_class}",
                }
            )
        return {"status": "reușit", "error": None, "rows": rows}
    except Exception as exc:
        return {"status": "eroare", "error": str(exc), "rows": []}


def _sample_labels(payload: dict[str, Any]) -> dict[str, int]:
    result = {}
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        key = properties.get("feature_key")
        label = properties.get("label", properties.get("mode"))
        if key is not None and label is not None:
            result[str(key)] = int(label)
    return result


def _correlation_geometry(
    feature: dict[str, Any],
    layer_id: str,
) -> tuple[dict[str, Any], str]:
    geometry = feature.get("geometry") or {}
    if layer_id == "osm_buildings":
        return geometry, "clasă dominantă pe suprafață"
    if layer_id in {"osm_roads", "osm_railways"}:
        affected = (
            feature.get("direct_geometry")
            or feature.get("buffer_geometry")
            or feature.get("clipped_geometry")
            or geometry
        )
        return affected, "eșantionare pe segmentul afectat"
    point = shape(geometry).representative_point()
    return (
        {"type": "Point", "coordinates": [point.x, point.y]},
        "punct reprezentativ",
    )


def dynamic_world_layer_definitions(result: dict[str, Any]) -> list[dict[str, Any]]:
    tiles = result.get("tiles", {})
    specifications = (
        ("dynamic_world_before", "Dynamic World BEFORE", "#419bdf", False),
        ("dynamic_world_after", "Dynamic World AFTER", "#397d49", False),
        ("dynamic_world_changes", "Modificări observate Dynamic World", "#facc15", False),
        (
            "dynamic_world_new_water",
            "Apă nouă evidențiată prin Dynamic World",
            "#0284c7",
            True,
        ),
        ("both_methods", "Apă nouă prin ambele metode", "#16a34a", False),
        ("only_sar", "Apă nouă doar SAR", "#22d3ee", False),
        ("only_dynamic_world", "Apă nouă doar Dynamic World", "#9333ea", False),
    )
    acquisition_dates = result.get("acquisition_dates", {})
    return [
        {
            "id": key,
            "name": (
                f"{name} ({acquisition_dates.get('before')})"
                if key == "dynamic_world_before" and acquisition_dates.get("before")
                else f"{name} ({acquisition_dates.get('after')})"
                if key == "dynamic_world_after" and acquisition_dates.get("after")
                else name
            ),
            "tile_url": (
                tiles.get(key, {}).get("url")
                if isinstance(tiles.get(key), dict)
                else tiles.get(key)
            ),
            "tile_status": (
                tiles.get(key, {}).get("status")
                if isinstance(tiles.get(key), dict)
                else "reușit" if tiles.get(key) else "tile indisponibil"
            ),
            "tile_error": (
                tiles.get(key, {}).get("error")
                if isinstance(tiles.get(key), dict)
                else None
            ),
            "color": color,
            "shown": shown,
        }
        for key, name, color, shown in specifications
    ]

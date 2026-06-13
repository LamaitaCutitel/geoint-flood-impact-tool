from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from src.gee.gee_tile_layers import ee_tile_url
from src.gee.sar_water_masks import (
    sar_water_area_metrics,
    sar_water_change_masks,
    sar_water_mask,
)
from src.gee.sentinel1_scene_explorer import selected_scene_image


SAR_THRESHOLD_PRESETS = {
    "VH": {"conservator": -20.0, "echilibrat": -18.0, "sensibil": -16.0},
    "VV": {"conservator": -17.0, "echilibrat": -15.0, "sensibil": -13.0},
}


def recommended_sar_threshold(polarization: str, mode: str) -> float:
    return SAR_THRESHOLD_PRESETS.get(
        polarization,
        SAR_THRESHOLD_PRESETS["VH"],
    ).get(mode, SAR_THRESHOLD_PRESETS["VH"]["echilibrat"])


@dataclass(frozen=True)
class SarParameters:
    water_threshold: float = -18.0
    smoothing_meters: int = 0
    minimum_connected_pixels: int = 8
    analysis_scale_meters: int = 10
    vectorization_scale_meters: int = 30
    minimum_polygon_area_m2: int = 1000
    geometry_simplification_tolerance_m: int = 10
    vectorization_best_effort: bool = True


def run_sar_analysis(
    ee: Any,
    aoi: Any,
    before_scene: dict[str, Any],
    after_scene: dict[str, Any],
    parameters: SarParameters,
) -> dict[str, Any]:
    started = perf_counter()
    before_image = selected_scene_image(
        ee,
        before_scene,
        aoi,
        smoothing_radius=parameters.smoothing_meters,
    )
    after_image = selected_scene_image(
        ee,
        after_scene,
        aoi,
        smoothing_radius=parameters.smoothing_meters,
    )
    before_water = sar_water_mask(
        before_image,
        parameters.water_threshold,
        aoi,
        parameters.minimum_connected_pixels,
    )
    after_water = sar_water_mask(
        after_image,
        parameters.water_threshold,
        aoi,
        parameters.minimum_connected_pixels,
    )
    changes = sar_water_change_masks(before_water, after_water, aoi)
    masks = {
        "sar_water_before": before_water,
        "sar_water_after": after_water,
        "sar_new_water": changes["sar_new_water"],
    }
    metrics = _metric_statuses(
        ee,
        masks,
        aoi,
        parameters.analysis_scale_meters,
    )
    tiles = {
        "sar_water_before": _tile_status(before_water, "SAR water BEFORE"),
        "sar_water_after": _tile_status(after_water, "SAR water AFTER"),
        "sar_new_water": _tile_status(changes["sar_new_water"], "SAR new water"),
    }
    vector_started = perf_counter()
    vectorization = _vector_geometry(
        ee,
        changes["sar_new_water"],
        aoi,
        scale_meters=parameters.vectorization_scale_meters,
        minimum_polygon_area_m2=parameters.minimum_polygon_area_m2,
        simplification_tolerance_m=parameters.geometry_simplification_tolerance_m,
        best_effort=parameters.vectorization_best_effort,
    )
    vectorization["duration_seconds"] = round(perf_counter() - vector_started, 3)
    return {
        "products": {**masks, **changes},
        "metrics": metrics,
        "tiles": tiles,
        "new_water_geometry": vectorization.get("geometry"),
        "new_water_display_geometry": vectorization.get("display_geometry"),
        "vectorization": vectorization,
        "parameters": {
            "polarization": before_scene.get("polarization"),
            "water_threshold": parameters.water_threshold,
            "smoothing_meters": parameters.smoothing_meters,
            "minimum_connected_pixels": parameters.minimum_connected_pixels,
            "analysis_scale_meters": parameters.analysis_scale_meters,
            "vectorization_scale_meters": parameters.vectorization_scale_meters,
            "minimum_polygon_area_m2": parameters.minimum_polygon_area_m2,
            "geometry_simplification_tolerance_m": (
                parameters.geometry_simplification_tolerance_m
            ),
            "vectorization_best_effort": parameters.vectorization_best_effort,
        },
        "warnings": (
            [
                "Scara vectorizării diferă de scara metricilor. Rasterul SAR "
                "rămâne produsul autoritativ pentru suprafață."
            ]
            if parameters.analysis_scale_meters
            != parameters.vectorization_scale_meters
            else []
        ),
        "duration_seconds": round(perf_counter() - started, 3),
        "vectorization_duration_seconds": vectorization["duration_seconds"],
    }


def _metric_statuses(
    ee: Any,
    masks: dict[str, Any],
    aoi: Any,
    scale_meters: int,
) -> dict[str, dict[str, Any]]:
    keys = (
        "sar_water_before_area_km2",
        "sar_water_after_area_km2",
        "sar_new_water_area_km2",
    )
    try:
        values = sar_water_area_metrics(ee, masks, aoi, scale_meters)
        return {
            key: {"status": "reușit", "value": values.get(key), "error": None}
            for key in keys
        }
    except Exception as exc:
        return {
            key: {"status": "eroare", "value": None, "error": str(exc)}
            for key in keys
        }


def _tile_status(image: Any, label: str) -> dict[str, Any]:
    try:
        url = ee_tile_url(image, label)
        if not url:
            raise RuntimeError("URL tile indisponibil")
        return {"status": "reușit", "url": url, "error": None}
    except Exception as exc:
        return {"status": "tile indisponibil", "url": None, "error": str(exc)}


def _vector_geometry(
    ee: Any,
    mask: Any,
    aoi: Any,
    *,
    scale_meters: int = 10,
    minimum_polygon_area_m2: int = 1000,
    simplification_tolerance_m: int = 10,
    best_effort: bool = True,
) -> dict[str, Any]:
    try:
        vectors = mask.reduceToVectors(
            geometry=aoi,
            scale=scale_meters,
            geometryType="polygon",
            eightConnected=True,
            maxPixels=1e8,
            bestEffort=best_effort,
        )
        vectors = vectors.map(
            lambda feature: feature.set(
                "area_m2",
                feature.geometry().area(maxError=max(1, scale_meters)),
            )
        ).filter(ee.Filter.gte("area_m2", minimum_polygon_area_m2))
        operational_geometry = vectors.geometry()
        display_geometry = operational_geometry.simplify(
            maxError=max(1, simplification_tolerance_m)
        )
        return {
            "status": "reușit",
            "geometry": operational_geometry.getInfo(),
            "display_geometry": display_geometry.getInfo(),
            "error": None,
            "scale_meters": scale_meters,
            "minimum_polygon_area_m2": minimum_polygon_area_m2,
            "simplification_tolerance_m": simplification_tolerance_m,
            "best_effort": best_effort,
        }
    except Exception as exc:
        return {
            "status": "eroare",
            "geometry": None,
            "display_geometry": None,
            "error": str(exc),
            "scale_meters": scale_meters,
            "minimum_polygon_area_m2": minimum_polygon_area_m2,
            "simplification_tolerance_m": simplification_tolerance_m,
            "best_effort": best_effort,
        }


def sar_layer_definitions(result: dict[str, Any]) -> list[dict[str, Any]]:
    tiles = result.get("tiles", {})
    before_tile = _normalized_tile(tiles.get("sar_water_before"))
    after_tile = _normalized_tile(tiles.get("sar_water_after"))
    new_water_tile = _normalized_tile(tiles.get("sar_new_water"))
    return [
        {
            "id": "sar_water_before",
            "name": "Apă observată BEFORE",
            "tile_url": before_tile.get("url"),
            "tile_status": before_tile.get("status"),
            "tile_error": before_tile.get("error"),
            "color": "#7dd3fc",
            "shown": False,
        },
        {
            "id": "sar_water_after",
            "name": "Apă observată AFTER",
            "tile_url": after_tile.get("url"),
            "tile_status": after_tile.get("status"),
            "tile_error": after_tile.get("error"),
            "color": "#2563eb",
            "shown": False,
        },
        {
            "id": "sar_new_water",
            "name": "Apă nouă evidențiată prin SAR",
            "tile_url": new_water_tile.get("url"),
            "tile_status": new_water_tile.get("status"),
            "tile_error": new_water_tile.get("error"),
            "color": "#22d3ee",
            "shown": True,
        },
    ]


def _normalized_tile(tile: Any) -> dict[str, Any]:
    if isinstance(tile, dict):
        return tile
    if isinstance(tile, str) and tile:
        return {"status": "reușit", "url": tile, "error": None}
    return {"status": "tile indisponibil", "url": None, "error": None}

from __future__ import annotations

from time import perf_counter
from typing import Any

from src.gee.sar_water_masks import sar_water_change_masks, sar_water_mask
from src.gee.sentinel1_scene_explorer import selected_scene_image
from src.impact_tool.sar import _metric_statuses, _tile_status


SAR_QA_THRESHOLDS = {
    "VH": (-20.0, -19.0, -18.0, -17.0, -16.0),
    "VV": (-17.0, -16.0, -15.0, -14.0, -13.0),
}
SAR_QA_BALANCED_THRESHOLD = {"VH": -18.0, "VV": -15.0}


def run_sar_threshold_sweep(
    ee: Any,
    aoi: Any,
    before_scene: dict[str, Any],
    after_scene: dict[str, Any],
    *,
    analysis_scale_meters: int = 10,
    smoothing_meters: int = 0,
    minimum_connected_pixels: int = 8,
    final_threshold: float,
) -> dict[str, Any]:
    polarization = before_scene.get("polarization", "VH")
    before_image = selected_scene_image(
        ee,
        before_scene,
        aoi,
        smoothing_radius=smoothing_meters,
    )
    after_image = selected_scene_image(
        ee,
        after_scene,
        aoi,
        smoothing_radius=smoothing_meters,
    )
    rows = []
    for threshold in SAR_QA_THRESHOLDS.get(
        polarization,
        SAR_QA_THRESHOLDS["VH"],
    ):
        started = perf_counter()
        before_water = sar_water_mask(
            before_image,
            threshold,
            aoi,
            minimum_connected_pixels,
        )
        after_water = sar_water_mask(
            after_image,
            threshold,
            aoi,
            minimum_connected_pixels,
        )
        changes = sar_water_change_masks(before_water, after_water, aoi)
        metrics = _metric_statuses(
            ee,
            {
                "sar_water_before": before_water,
                "sar_water_after": after_water,
                "sar_new_water": changes["sar_new_water"],
            },
            aoi,
            analysis_scale_meters,
        )
        rows.append(
            {
                "threshold_db": threshold,
                "status": (
                    "reușit"
                    if all(item.get("status") == "reușit" for item in metrics.values())
                    else "eroare"
                ),
                "water_before_km2": _metric_value(
                    metrics["sar_water_before_area_km2"]
                ),
                "water_after_km2": _metric_value(
                    metrics["sar_water_after_area_km2"]
                ),
                "new_water_km2": _metric_value(
                    metrics["sar_new_water_area_km2"]
                ),
                "duration_seconds": round(perf_counter() - started, 3),
                "error": _metric_errors(metrics),
            }
        )
    balanced = SAR_QA_BALANCED_THRESHOLD.get(polarization)
    balanced_row = next(
        (row for row in rows if row["threshold_db"] == balanced),
        None,
    )
    balanced_value = (balanced_row or {}).get("new_water_km2")
    for row in rows:
        value = row.get("new_water_km2")
        row["difference_from_balanced_percent"] = _percent_difference(
            value,
            balanced_value,
        )
    final_masks = _qa_layers(
        before_image,
        after_image,
        aoi,
        final_threshold,
        minimum_connected_pixels,
    )
    return {
        "status": (
            "reușit" if any(row["status"] == "reușit" for row in rows) else "eroare"
        ),
        "polarization": polarization,
        "balanced_threshold_db": balanced,
        "final_threshold_db": final_threshold,
        "analysis_scale_meters": analysis_scale_meters,
        "rows": rows,
        "layers": final_masks,
        "manual_checklist": [
            "luciu de apă existent",
            "umbre radar",
            "teren urban",
            "vegetație inundată",
            "artefacte la marginea scenei",
        ],
    }


def sar_qa_layer_definitions(result: dict[str, Any]) -> list[dict[str, Any]]:
    names = {
        "qa_persistent_water": "QA - apă persistentă",
        "qa_water_loss": "QA - pierdere de apă",
        "qa_delta_backscatter": "QA - delta backscatter AFTER - BEFORE",
    }
    return [
        {
            "id": layer_id,
            "name": names[layer_id],
            "tile_url": status.get("url"),
            "tile_status": status.get("status"),
            "tile_error": status.get("error"),
            "shown": False,
        }
        for layer_id, status in result.get("layers", {}).items()
        if layer_id in names
    ]


def sar_qa_chart_data(result: dict[str, Any]) -> dict[str, float]:
    return {
        str(row["threshold_db"]): float(row["new_water_km2"])
        for row in result.get("rows", [])
        if row.get("status") == "reușit" and row.get("new_water_km2") is not None
    }


def _qa_layers(
    before_image: Any,
    after_image: Any,
    aoi: Any,
    threshold: float,
    minimum_connected_pixels: int,
) -> dict[str, dict[str, Any]]:
    before_water = sar_water_mask(
        before_image,
        threshold,
        aoi,
        minimum_connected_pixels,
    )
    after_water = sar_water_mask(
        after_image,
        threshold,
        aoi,
        minimum_connected_pixels,
    )
    changes = sar_water_change_masks(before_water, after_water, aoi)
    layers = {
        "qa_persistent_water": _tile_status(
            changes["sar_persistent_water"],
            "QA persistent water",
        ),
        "qa_water_loss": _tile_status(
            changes["sar_water_loss"],
            "QA water loss",
        ),
    }
    try:
        delta = after_image.subtract(before_image).clip(aoi)
        layers["qa_delta_backscatter"] = _tile_status(
            delta,
            "QA delta backscatter",
        )
    except Exception as exc:
        layers["qa_delta_backscatter"] = {
            "status": "tile indisponibil",
            "url": None,
            "error": str(exc),
        }
    return layers


def _metric_value(metric: dict[str, Any]) -> float | None:
    if metric.get("status") != "reușit" or metric.get("value") is None:
        return None
    return float(metric["value"])


def _metric_errors(metrics: dict[str, dict[str, Any]]) -> str | None:
    errors = [
        str(metric.get("error"))
        for metric in metrics.values()
        if metric.get("status") != "reușit" and metric.get("error")
    ]
    return "; ".join(errors) or None


def _percent_difference(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline in {None, 0}:
        return None
    return round(((value - baseline) / baseline) * 100, 2)

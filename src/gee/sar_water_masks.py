from __future__ import annotations

from typing import Any

SAR_WATER_THRESHOLDS = {
    "VH": {
        "Conservator": -20.0,
        "Echilibrat": -18.0,
        "Sensibil": -16.0,
    },
    "VV": {
        "Conservator": -17.0,
        "Echilibrat": -15.0,
        "Sensibil": -13.0,
    },
}


def sar_water_threshold_for_mode(polarization: str, mode: str, manual_threshold: float) -> float:
    if mode == "Manual":
        return manual_threshold
    return SAR_WATER_THRESHOLDS.get(polarization, SAR_WATER_THRESHOLDS["VH"]).get(mode, manual_threshold)


def sar_water_mask(
    image: Any,
    threshold: float,
    aoi: Any,
    minimum_connected_pixels: int = 0,
) -> Any:
    water = image.lt(threshold).selfMask().clip(aoi)
    if minimum_connected_pixels > 0:
        connected = water.connectedPixelCount(100, True)
        water = water.updateMask(connected.gte(minimum_connected_pixels)).selfMask().clip(aoi)
    return water


def sar_water_change_masks(water_before: Any, water_after: Any, aoi: Any) -> dict[str, Any]:
    before = water_before.unmask(0)
    after = water_after.unmask(0)
    new_water = after.And(before.Not()).selfMask().clip(aoi)
    persistent_water = after.And(before).selfMask().clip(aoi)
    water_loss = before.And(after.Not()).selfMask().clip(aoi)
    return {
        "sar_new_water": new_water,
        "sar_persistent_water": persistent_water,
        "sar_water_loss": water_loss,
    }


def sar_dynamic_world_overlap(sar_new_water: Any, dynamic_world_new_water: Any, aoi: Any) -> dict[str, Any]:
    sar = sar_new_water.unmask(0)
    dynamic_world = dynamic_world_new_water.unmask(0)
    overlap = sar.And(dynamic_world).selfMask().clip(aoi)
    only_sar = sar.And(dynamic_world.Not()).selfMask().clip(aoi)
    only_dynamic_world = dynamic_world.And(sar.Not()).selfMask().clip(aoi)
    return {
        "sar_dynamic_world_new_water_overlap": overlap,
        "new_water_only_sar": only_sar,
        "new_water_only_dynamic_world": only_dynamic_world,
    }


def sar_water_area_metrics(ee: Any, masks: dict[str, Any], aoi: Any, scale: int) -> dict[str, float]:
    area_image = None
    band_names = []
    for key, mask in masks.items():
        band_name = f"{key}_area_km2"
        band_names.append(band_name)
        band = (
            ee.Image.pixelArea()
            .divide(1_000_000)
            .updateMask(mask)
            .rename(band_name)
        )
        area_image = band if area_image is None else area_image.addBands(band)
    if area_image is None:
        return {}
    values = area_image.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e10,
        bestEffort=False,
    ).getInfo()
    return {
        band_name: round(float(values.get(band_name) or 0), 4)
        for band_name in band_names
    }


def overlap_percent(overlap_area_km2: float, sar_new_water_area_km2: float) -> float:
    if not sar_new_water_area_km2:
        return 0.0
    return round((overlap_area_km2 / sar_new_water_area_km2) * 100, 2)

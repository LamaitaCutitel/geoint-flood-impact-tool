from __future__ import annotations

from typing import Any

from config.settings import LAND_COVER_CLASSES
from src.gee.gee_config import COLLECTIONS
from src.utils.area_utils import dominant_class, square_meters_to_square_kilometers


def dynamic_world_mode(ee: Any, aoi: Any, start_date: str, end_date: str) -> Any:
    return (
        ee.ImageCollection(COLLECTIONS.dynamic_world)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .select("label")
        .mode()
        .clip(aoi)
    )


def nearest_dynamic_world_image(
    ee: Any,
    aoi: Any,
    target_date: str,
    window_days: int = 15,
) -> tuple[Any, str]:
    target = ee.Date(target_date)
    collection = (
        ee.ImageCollection(COLLECTIONS.dynamic_world)
        .filterBounds(aoi)
        .filterDate(target.advance(-window_days, "day"), target.advance(window_days + 1, "day"))
        .select("label")
        .map(
            lambda image: image.set(
                "distance_to_target",
                image.date().difference(target, "day").abs(),
            )
        )
        .sort("distance_to_target")
    )
    count = int(collection.size().getInfo())
    if count == 0:
        raise RuntimeError(
            f"Dynamic World nu are observații în intervalul de ±{window_days} zile "
            f"față de {target_date}."
        )
    image = ee.Image(collection.first()).clip(aoi)
    acquisition_date = (
        ee.Date(image.get("system:time_start")).format("YYYY-MM-dd").getInfo()
    )
    return image, acquisition_date


def dynamic_world_change_map(ee: Any, before: Any, after: Any, aoi: Any) -> Any:
    water_class = 0
    no_change = before.eq(after)
    new_water = after.eq(water_class).And(before.neq(water_class))
    water_loss = before.eq(water_class).And(after.neq(water_class))
    other_change = before.neq(after).And(new_water.Not()).And(water_loss.Not())
    return (
        ee.Image(0)
        .where(no_change, 1)
        .where(other_change, 2)
        .where(water_loss, 3)
        .where(new_water, 4)
        .rename("land_cover_changes")
        .clip(aoi)
    )


def dynamic_world_water_change_masks(before: Any, after: Any, flood_mask: Any, aoi: Any) -> dict[str, Any]:
    water_class = 0
    new_water_raw = after.eq(water_class).And(before.neq(water_class))
    water_loss_raw = before.eq(water_class).And(after.neq(water_class))
    other_change = before.neq(after).And(new_water_raw.Not()).And(water_loss_raw.Not()).selfMask().clip(aoi)
    new_water = new_water_raw.selfMask().clip(aoi)
    water_loss = water_loss_raw.selfMask().clip(aoi)
    sar_new_water_intersection = flood_mask.updateMask(new_water).selfMask().clip(aoi)
    return {
        "dynamic_world_new_water": new_water,
        "dynamic_world_water_loss": water_loss,
        "dynamic_world_other_change": other_change,
        "sar_dynamic_world_new_water_intersection": sar_new_water_intersection,
    }


def mask_area_km2(ee: Any, mask: Any, aoi: Any, scale: int) -> float:
    try:
        area_image = mask.multiply(ee.Image.pixelArea())
        stats = area_image.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()
        area_sqm = next(iter(stats.values()), 0) if stats else 0
        return square_meters_to_square_kilometers(area_sqm)
    except Exception:
        return 0.0


def land_cover_intersection_stats(
    ee: Any,
    land_cover: Any,
    flood_mask: Any,
    aoi: Any,
    scale: int,
) -> dict[str, float]:
    stats: dict[str, float] = {name: 0.0 for name in LAND_COVER_CLASSES.values()}
    try:
        pixel_area = ee.Image.pixelArea().addBands(land_cover.rename("label"))
        grouped = pixel_area.updateMask(flood_mask).reduceRegion(
            reducer=ee.Reducer.sum().group(groupField=1, groupName="label"),
            geometry=aoi,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()
    except Exception:
        return stats

    for item in grouped.get("groups", []):
        label = int(item.get("label"))
        class_name = LAND_COVER_CLASSES.get(label, f"class_{label}")
        stats[class_name] = square_meters_to_square_kilometers(item.get("sum", 0))
    return stats


def summarize_land_cover(stats: dict[str, float]) -> dict[str, str | float]:
    return {
        "dominant_class": dominant_class(stats),
        "crops_intersected_km2": round(stats.get("crops", 0.0), 4),
        "built_up_intersected_km2": round(stats.get("built", 0.0), 4),
        "vegetation_intersected_km2": round(
            stats.get("trees", 0.0)
            + stats.get("grass", 0.0)
            + stats.get("flooded vegetation", 0.0)
            + stats.get("shrub and scrub", 0.0),
            4,
        ),
    }

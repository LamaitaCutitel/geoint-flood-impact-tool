from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.gee.gee_config import COLLECTIONS


@dataclass
class Sentinel2Products:
    before_collection: Any
    after_collection: Any
    scene_count_before: int
    scene_count_after: int
    rgb_before: Any | None
    rgb_after: Any | None
    indices: dict[str, Any]
    warnings: list[str]


def sentinel2_collection(ee: Any, aoi: Any, start_date: str, end_date: str) -> Any:
    return (
        ee.ImageCollection(COLLECTIONS.sentinel2)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 70))
        .map(lambda image: image.updateMask(image.select("SCL").neq(9)).updateMask(image.select("SCL").neq(10)))
    )


def build_sentinel2_products(
    ee: Any,
    aoi: Any,
    before_start: str,
    before_end: str,
    after_start: str,
    after_end: str,
) -> Sentinel2Products:
    warnings: list[str] = []
    before_collection = sentinel2_collection(ee, aoi, before_start, before_end)
    after_collection = sentinel2_collection(ee, aoi, after_start, after_end)
    before_count = _count(before_collection)
    after_count = _count(after_collection)
    if before_count == 0:
        warnings.append("Nu exista compozit Sentinel-2 before disponibil din cauza acoperirii cu nori sau lipsei scenelor.")
    if after_count == 0:
        warnings.append("Nu exista compozit Sentinel-2 after disponibil din cauza acoperirii cu nori sau lipsei scenelor.")

    rgb_before = before_collection.median().clip(aoi) if before_count else None
    rgb_after = after_collection.median().clip(aoi) if after_count else None
    indices: dict[str, Any] = {}
    if rgb_before:
        indices.update(_indices_for(rgb_before, "before"))
    if rgb_after:
        indices.update(_indices_for(rgb_after, "after"))
    if rgb_before and rgb_after:
        for name in ["ndwi", "mndwi", "ndvi", "ndmi"]:
            indices[f"delta_{name}"] = indices[f"{name}_after"].subtract(indices[f"{name}_before"]).rename(f"delta_{name}").clip(aoi)

    return Sentinel2Products(
        before_collection=before_collection,
        after_collection=after_collection,
        scene_count_before=before_count,
        scene_count_after=after_count,
        rgb_before=rgb_before,
        rgb_after=rgb_after,
        indices=indices,
        warnings=warnings,
    )


def sentinel2_rgb_context(ee: Any, aoi: Any, start_date: str, end_date: str) -> Any:
    collection = sentinel2_collection(ee, aoi, start_date, end_date)
    return collection.median().select(["B4", "B3", "B2"]).clip(aoi)


def _indices_for(image: Any, suffix: str) -> dict[str, Any]:
    return {
        f"ndwi_{suffix}": image.normalizedDifference(["B3", "B8"]).rename(f"ndwi_{suffix}"),
        f"mndwi_{suffix}": image.normalizedDifference(["B3", "B11"]).rename(f"mndwi_{suffix}"),
        f"ndvi_{suffix}": image.normalizedDifference(["B8", "B4"]).rename(f"ndvi_{suffix}"),
        f"ndmi_{suffix}": image.normalizedDifference(["B8", "B11"]).rename(f"ndmi_{suffix}"),
    }


def _count(collection: Any) -> int:
    try:
        return int(collection.size().getInfo())
    except Exception:
        return 0

from __future__ import annotations

from datetime import date
from typing import Any

from src.gee.gee_config import COLLECTIONS


def build_aoi(ee: Any, bbox: list[float]) -> Any:
    return ee.Geometry.Rectangle(bbox)


def build_aoi_from_geometry(ee: Any, geometry: dict[str, Any] | None, bbox: list[float]) -> Any:
    if geometry:
        return ee.Geometry(geometry)
    return build_aoi(ee, bbox)


def get_sentinel1_collection(
    ee: Any,
    aoi: Any,
    start_date: date | str,
    end_date: date | str,
    polarization: str = "VH",
    orbit_pass: str = "BOTH",
) -> Any:
    collection = (
        ee.ImageCollection(COLLECTIONS.sentinel1)
        .filterBounds(aoi)
        .filterDate(str(start_date), str(end_date))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", polarization))
        .select(polarization)
    )
    if orbit_pass != "BOTH":
        collection = collection.filter(ee.Filter.eq("orbitProperties_pass", orbit_pass))
    return collection


def count_scenes(collection: Any) -> int:
    try:
        return int(collection.size().getInfo())
    except Exception:
        return 0

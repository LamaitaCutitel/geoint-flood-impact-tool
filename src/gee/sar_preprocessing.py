from __future__ import annotations

from typing import Any


def median_composite(collection: Any) -> Any:
    return collection.median()


def minimum_composite(collection: Any) -> Any:
    return collection.min()


def smooth_sar(image: Any, ee: Any, radius_meters: int) -> Any:
    if radius_meters <= 0:
        return image
    kernel = ee.Kernel.circle(radius=radius_meters, units="meters", normalize=True)
    return image.focal_mean(kernel=kernel, iterations=1)


def build_before_after_composites(
    before_collection: Any,
    after_collection: Any,
    ee: Any,
    smoothing_radius: int,
    aoi: Any | None = None,
) -> tuple[Any, Any]:
    before = smooth_sar(median_composite(before_collection), ee, smoothing_radius)
    after = smooth_sar(median_composite(after_collection), ee, smoothing_radius)
    if aoi is not None:
        before = before.clip(aoi)
        after = after.clip(aoi)
    return before, after

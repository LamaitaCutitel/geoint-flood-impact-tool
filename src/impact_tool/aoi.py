from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform


LARGE_AOI_RATIO = 0.75


@dataclass(frozen=True)
class AreaMetadata:
    geometry: dict[str, Any]
    bbox: list[float]
    centroid: list[float]
    area_km2: float
    area_hash: str
    warnings: list[str]


@dataclass(frozen=True)
class AoiValidation:
    valid: bool
    geometry: dict[str, Any] | None
    warnings: list[str]
    errors: list[str]


def geometry_from_drawing(drawing: dict[str, Any] | None) -> dict[str, Any] | None:
    if not drawing:
        return None
    if drawing.get("type") == "Feature":
        return drawing.get("geometry")
    if drawing.get("type") in {"Polygon", "MultiPolygon"}:
        return drawing
    geometry = drawing.get("geometry")
    return geometry if isinstance(geometry, dict) else None


def validate_aoi(
    geometry: dict[str, Any] | None,
    county_geometry: dict[str, Any] | None,
) -> AoiValidation:
    if not geometry:
        return AoiValidation(False, None, [], ["AOI-ul este gol."])
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return AoiValidation(False, None, [], ["AOI-ul trebuie să fie un poligon."])
    try:
        aoi_shape = shape(geometry)
    except (TypeError, ValueError):
        return AoiValidation(False, None, [], ["Geometria AOI este invalidă."])
    if aoi_shape.is_empty or not aoi_shape.is_valid or aoi_shape.area <= 0:
        return AoiValidation(False, None, [], ["Suprafața AOI este nulă sau invalidă."])

    warnings: list[str] = []
    validated_geometry = geometry
    if county_geometry:
        try:
            county_shape = shape(county_geometry)
        except (TypeError, ValueError):
            return AoiValidation(
                False,
                None,
                [],
                ["Geometria județului selectat este invalidă."],
            )
        if not aoi_shape.intersects(county_shape):
            return AoiValidation(
                False,
                None,
                [],
                ["AOI-ul nu intersectează județul selectat."],
            )
        if not aoi_shape.within(county_shape):
            intersection = aoi_shape.intersection(county_shape)
            if intersection.is_empty or intersection.geom_type not in {
                "Polygon",
                "MultiPolygon",
            }:
                return AoiValidation(
                    False,
                    None,
                    [],
                    ["Intersecția AOI cu județul nu produce o suprafață validă."],
                )
            validated_geometry = mapping(intersection)
            aoi_shape = intersection
            warnings.append(
                "AOI-ul depășea limita județului și a fost decupat la intersecția exactă."
            )

        county_area = area_km2(county_geometry)
        if county_area and area_km2(validated_geometry) / county_area >= LARGE_AOI_RATIO:
            warnings.append(
                "AOI-ul acoperă o mare parte din județ; analiza poate necesita mai mult timp."
            )
    return AoiValidation(True, validated_geometry, warnings, [])


def area_metadata(
    geometry: dict[str, Any],
    warnings: list[str] | None = None,
) -> AreaMetadata:
    return AreaMetadata(
        geometry=geometry,
        bbox=geometry_bbox(geometry),
        centroid=[round(value, 8) for value in geometry_centroid(geometry)],
        area_km2=round(area_km2(geometry), 4),
        area_hash=geometry_hash(geometry),
        warnings=list(warnings or []),
    )


def geometry_bbox(geometry: dict[str, Any]) -> list[float]:
    geometry_shape = shape(geometry)
    return list(geometry_shape.bounds) if not geometry_shape.is_empty else []


def geometry_centroid(geometry: dict[str, Any]) -> list[float]:
    geometry_shape = shape(geometry)
    if geometry_shape.is_empty:
        return []
    centroid = geometry_shape.centroid
    return [centroid.x, centroid.y]


def area_km2(geometry: dict[str, Any]) -> float:
    geometry_shape = shape(geometry)
    if geometry_shape.is_empty:
        return 0.0
    transformer = Transformer.from_crs(
        "EPSG:4326",
        "EPSG:3035",
        always_xy=True,
    )
    projected = transform(transformer.transform, geometry_shape)
    return projected.area / 1_000_000.0


def geometry_hash(geometry: dict[str, Any]) -> str:
    serialized = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

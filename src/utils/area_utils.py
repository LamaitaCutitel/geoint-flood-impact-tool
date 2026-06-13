from __future__ import annotations

from typing import Mapping


SQM_PER_SQKM = 1_000_000


def square_meters_to_square_kilometers(area_sqm: float | int | None) -> float:
    if area_sqm is None:
        return 0.0
    if area_sqm < 0:
        raise ValueError("Area cannot be negative.")
    return round(float(area_sqm) / SQM_PER_SQKM, 4)


def hectares_to_square_kilometers(area_ha: float | int | None) -> float:
    if area_ha is None:
        return 0.0
    if area_ha < 0:
        raise ValueError("Area cannot be negative.")
    return round(float(area_ha) / 100, 4)


def dominant_class(area_by_class: Mapping[str, float]) -> str:
    positive = {name: value for name, value in area_by_class.items() if value > 0}
    if not positive:
        return "not available"
    return max(positive.items(), key=lambda item: item[1])[0]


def sum_selected_classes(area_by_class: Mapping[str, float], classes: list[str]) -> float:
    return round(sum(float(area_by_class.get(name, 0.0)) for name in classes), 4)

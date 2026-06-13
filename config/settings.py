from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"
CACHE_DIR = OUTPUT_DIR / "cache"

GEE_S1_COLLECTION = "COPERNICUS/S1_GRD"
GEE_DYNAMIC_WORLD_COLLECTION = "GOOGLE/DYNAMICWORLD/V1"
GEE_SENTINEL2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

METHODOLOGICAL_NOTE = (
    "Rezultatele reprezinta produse GEOINT preliminare de suport decizional. "
    "Extinderea detectata automat prin Sentinel-1 SAR poate diferi de situatia "
    "reala din teren din cauza momentului achizitiei, rezolutiei spatiale, "
    "pragurilor utilizate, zgomotului radar, vegetatiei si limitarilor datelor "
    "auxiliare."
)

GALATI_PRESET = {
    "name": "Galati - September 2024 Floods",
    "event_date": date(2024, 9, 14),
    "before_start_date": date(2024, 8, 20),
    "before_end_date": date(2024, 9, 5),
    "after_start_date": date(2024, 9, 14),
    "after_end_date": date(2024, 9, 25),
    "bbox": [27.45, 45.35, 28.25, 46.05],
    "center": [45.70, 27.85],
    "zoom": 10,
}

LAND_COVER_CLASSES = {
    0: "water",
    1: "trees",
    2: "grass",
    3: "flooded vegetation",
    4: "crops",
    5: "shrub and scrub",
    6: "built",
    7: "bare",
    8: "snow and ice",
}

PROFILE_SCALES = {
    "Rapid preview": 40,
    "Standard": 20,
    "Detailed export": 10,
}


@dataclass(frozen=True)
class AppSettings:
    gee_project_id: str | None
    reports_dir: Path = REPORTS_DIR
    cache_dir: Path = CACHE_DIR
    methodological_note: str = METHODOLOGICAL_NOTE


def load_settings() -> AppSettings:
    load_dotenv(PROJECT_ROOT / ".env")
    project_id = os.getenv("GEE_PROJECT_ID") or None
    return AppSettings(gee_project_id=project_id)


def ensure_output_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def validate_analysis_parameters(params: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    required_dates = [
        "before_start_date",
        "before_end_date",
        "after_start_date",
        "after_end_date",
    ]
    missing = [name for name in required_dates if not params.get(name)]
    if missing:
        warnings.append(f"Missing date parameters: {', '.join(missing)}")
        return warnings

    if params["before_start_date"] > params["before_end_date"]:
        warnings.append("Before start date must be before before end date.")
    if params["after_start_date"] > params["after_end_date"]:
        warnings.append("After start date must be before after end date.")
    if params.get("polarization") not in {"VH", "VV"}:
        warnings.append("Polarization must be VH or VV.")
    if params.get("orbit_pass") not in {"BOTH", "ASCENDING", "DESCENDING"}:
        warnings.append("Orbit pass must be BOTH, ASCENDING, or DESCENDING.")
    threshold = float(params.get("threshold", 1.25))
    if threshold <= 0:
        warnings.append("SAR threshold must be positive.")
    scale = int(params.get("scale", 20))
    if scale not in {10, 20, 30, 40, 50}:
        warnings.append("Scale should be one of 10, 20, 30, 40, or 50 meters.")
    return warnings

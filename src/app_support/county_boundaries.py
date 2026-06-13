from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import unicodedata
from urllib.request import urlopen

from config.settings import PROJECT_ROOT


BOUNDARY_DIR = PROJECT_ROOT / "data" / "boundaries"
ROMANIA_COUNTIES_PATH = BOUNDARY_DIR / "romania_counties.geojson"
GISCO_NUTS3_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_01M_2024_4326_LEVL_3.geojson"
)

COUNTY_NAME_FIXES = {
    "Bucureşti": "Bucuresti",
    "Bistriţa-Năsăud": "Bistrita-Nasaud",
    "Caraş-Severin": "Caras-Severin",
    "Galaţi": "Galati",
    "Iaşi": "Iasi",
    "Maramureş": "Maramures",
    "Mehedinţi": "Mehedinti",
    "Mureş": "Mures",
    "Neamţ": "Neamt",
    "Timiş": "Timis",
    "Vâlcea": "Valcea",
}


@dataclass(frozen=True)
class CountyBoundaryResult:
    geojson: dict[str, Any] | None
    path: Path
    warnings: list[str]
    downloaded: bool = False

    @property
    def available(self) -> bool:
        return bool(self.geojson and self.geojson.get("features"))


def load_or_download_counties() -> CountyBoundaryResult:
    warnings: list[str] = []
    if ROMANIA_COUNTIES_PATH.exists():
        return CountyBoundaryResult(_read_geojson(ROMANIA_COUNTIES_PATH), ROMANIA_COUNTIES_PATH, warnings)

    try:
        BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
        with urlopen(GISCO_NUTS3_URL, timeout=20) as response:
            raw = json.loads(response.read().decode("utf-8"))
        features = [
            feature
            for feature in raw.get("features", [])
            if feature.get("properties", {}).get("CNTR_CODE") == "RO"
        ]
        geojson = {
            "type": "FeatureCollection",
            "name": "romania_counties_nuts3_2024",
            "source": "Eurostat GISCO NUTS 2024 level 3",
            "features": features,
        }
        ROMANIA_COUNTIES_PATH.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
        return CountyBoundaryResult(geojson, ROMANIA_COUNTIES_PATH, warnings, downloaded=True)
    except Exception as exc:
        warnings.append(
            "Nu am putut incarca limitele judetelor. Verifica fisierul "
            f"{ROMANIA_COUNTIES_PATH} sau conexiunea catre Eurostat GISCO. Detalii: {exc}"
        )
        return CountyBoundaryResult(None, ROMANIA_COUNTIES_PATH, warnings)


def county_names(geojson: dict[str, Any]) -> list[str]:
    return sorted({county_display_name(feature) for feature in geojson.get("features", [])})


def county_display_name(feature: dict[str, Any]) -> str:
    props = feature.get("properties", {})
    raw_name = props.get("NAME_LATN") or props.get("NUTS_NAME") or props.get("NAME") or "Necunoscut"
    return normalize_county_name(raw_name)


def normalize_county_name(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    if raw_name in COUNTY_NAME_FIXES:
        return COUNTY_NAME_FIXES[raw_name]
    raw_name = raw_name.replace("Å£", "t").replace("ÅŸ", "s").replace("Äƒ", "a")
    ascii_name = unicodedata.normalize("NFKD", raw_name).encode("ascii", "ignore").decode("ascii")
    return COUNTY_NAME_FIXES.get(ascii_name, ascii_name)


def selected_county_feature(geojson: dict[str, Any], county_name: str) -> dict[str, Any] | None:
    for feature in geojson.get("features", []):
        if county_display_name(feature) == county_name:
            return feature
    return None


def feature_bbox(feature: dict[str, Any] | None) -> list[float]:
    if not feature:
        return [20.2, 43.6, 29.8, 48.4]
    coords = _flatten_coordinates(feature.get("geometry", {}).get("coordinates", []))
    if not coords:
        return [20.2, 43.6, 29.8, 48.4]
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def bbox_center(bbox: list[float]) -> list[float]:
    west, south, east, north = bbox
    return [(south + north) / 2, (west + east) / 2]


def zoom_for_bbox(bbox: list[float]) -> int:
    width = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]))
    if width > 4:
        return 7
    if width > 2:
        return 8
    if width > 1:
        return 9
    return 10


def county_geometry(feature: dict[str, Any] | None) -> dict[str, Any] | None:
    if not feature:
        return None
    return feature.get("geometry")


def _read_geojson(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_coordinates(coordinates: Any) -> list[list[float]]:
    if not coordinates:
        return []
    if isinstance(coordinates[0], (float, int)):
        return [coordinates]
    points: list[list[float]] = []
    for item in coordinates:
        points.extend(_flatten_coordinates(item))
    return points

from __future__ import annotations

from typing import Any

import folium

from src.app_support.layer_styles import vis_params_by_display_name


VIS_PARAMS = {
    "Sentinel-1 SAR before": {"min": -25, "max": 0, "palette": ["111827", "e5e7eb"]},
    "Sentinel-1 SAR after": {"min": -25, "max": 0, "palette": ["111827", "e5e7eb"]},
    "SAR change": {"min": 0.8, "max": 2.0, "palette": ["2563eb", "facc15", "dc2626"]},
    "SAR difference": {"bands": ["sar_difference"], "min": -5, "max": 5, "palette": ["2563eb", "f8fafc", "dc2626"]},
    "SAR ratio": {"bands": ["sar_ratio"], "min": 0.8, "max": 2.0, "palette": ["2563eb", "facc15", "dc2626"]},
    "SAR water BEFORE": {"palette": ["7dd3fc"]},
    "SAR water AFTER": {"palette": ["2563eb"]},
    "SAR new water": {"palette": ["22d3ee"]},
    "SAR persistent water": {"palette": ["1e3a8a"]},
    "SAR water loss": {"palette": ["f97316"]},
    "detected flood extent": {"palette": ["ef4444"]},
    "SAR flood extent filtrat": {"palette": ["be185d"]},
    "land cover": {
        "min": 0,
        "max": 8,
        "palette": [
            "419bdf",
            "397d49",
            "88b053",
            "7a87c6",
            "e49635",
            "dfc35a",
            "c4281b",
            "a59b8f",
            "b39fe1",
        ],
    },
    "Sentinel-2 RGB": {"min": 0, "max": 3000, "bands": ["B4", "B3", "B2"]},
    "RGB before": {"min": 0, "max": 3000, "bands": ["B4", "B3", "B2"]},
    "RGB after": {"min": 0, "max": 3000, "bands": ["B4", "B3", "B2"]},
    "NDWI before": {"min": -1, "max": 1, "palette": ["8b5cf6", "f8fafc", "0284c7"]},
    "NDWI after": {"min": -1, "max": 1, "palette": ["8b5cf6", "f8fafc", "0284c7"]},
    "Delta NDWI": {"min": -0.5, "max": 0.5, "palette": ["dc2626", "f8fafc", "0284c7"]},
    "MNDWI before": {"min": -1, "max": 1, "palette": ["7c2d12", "f8fafc", "0e7490"]},
    "MNDWI after": {"min": -1, "max": 1, "palette": ["7c2d12", "f8fafc", "0e7490"]},
    "Delta MNDWI": {"min": -0.5, "max": 0.5, "palette": ["dc2626", "f8fafc", "0891b2"]},
    "NDVI before": {"min": -1, "max": 1, "palette": ["a16207", "f8fafc", "15803d"]},
    "NDVI after": {"min": -1, "max": 1, "palette": ["a16207", "f8fafc", "15803d"]},
    "Delta NDVI": {"min": -0.5, "max": 0.5, "palette": ["dc2626", "f8fafc", "16a34a"]},
    "NDMI before": {"min": -1, "max": 1, "palette": ["92400e", "f8fafc", "0369a1"]},
    "NDMI after": {"min": -1, "max": 1, "palette": ["92400e", "f8fafc", "0369a1"]},
    "Delta NDMI": {"min": -0.5, "max": 0.5, "palette": ["dc2626", "f8fafc", "2563eb"]},
    "Dynamic World before": {
        "min": 0,
        "max": 8,
        "palette": ["419bdf", "397d49", "88b053", "7a87c6", "e49635", "dfc35a", "c4281b", "a59b8f", "b39fe1"],
    },
    "Dynamic World after": {
        "min": 0,
        "max": 8,
        "palette": ["419bdf", "397d49", "88b053", "7a87c6", "e49635", "dfc35a", "c4281b", "a59b8f", "b39fe1"],
    },
    "Land cover changes": {
        "min": 1,
        "max": 4,
        "palette": ["e5e7eb", "facc15", "fb7185", "0284c7"],
    },
    "Dynamic World - apa noua": {"palette": ["0284c7"]},
    "Dynamic World - pierdere apa": {"palette": ["fb7185"]},
    "Dynamic World - alte diferente": {"palette": ["facc15"]},
    "Intersectie SAR x apa noua Dynamic World": {"palette": ["7c3aed"]},
    "SAR x Dynamic World new water overlap": {"palette": ["16a34a"]},
    "New water only SAR": {"palette": ["67e8f9"]},
    "New water only Dynamic World": {"palette": ["9333ea"]},
}
VIS_PARAMS.update(vis_params_by_display_name())


def add_ee_tile_layer(
    folium_map: folium.Map,
    ee_image: Any,
    name: str,
    shown: bool = False,
) -> folium.raster_layers.TileLayer | None:
    try:
        tile = ee_image.getMapId(VIS_PARAMS.get(name, {}))
        layer = folium.TileLayer(
            tiles=tile["tile_fetcher"].url_format,
            attr="Google Earth Engine",
            name=name,
            overlay=True,
            control=True,
            show=shown,
        )
        layer.add_to(folium_map)
        return layer
    except Exception:
        return None


def ee_tile_url(ee_image: Any, name: str) -> str | None:
    try:
        tile = ee_image.getMapId(VIS_PARAMS.get(name, {}))
        return tile["tile_fetcher"].url_format
    except Exception:
        return None

from __future__ import annotations

from typing import Any

import folium
from folium.plugins import Draw, Fullscreen, MeasureControl

from src.app_support.county_boundaries import bbox_center, feature_bbox, selected_county_feature
from src.impact_tool.map.layers import (
    add_aoi_layer,
    add_buffer_layer,
    add_county_outlines,
    add_osm_layers,
    add_tile_layers,
)
from src.impact_tool.map.legend import ImpactLegend, legend_entries
from src.impact_tool.map.swipe import LayerCompareControl, SarSwipeControl
from src.impact_tool.map.tools import FocusLocation, NavigationControl


ROMANIA_CENTER = [45.9432, 24.9668]


def _geometry_bounds(geometry: dict[str, Any] | None) -> list[list[float]] | None:
    if not geometry:
        return None
    points: list[list[float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and all(isinstance(item, (int, float)) for item in value[:2])
        ):
            points.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(geometry.get("coordinates", []))
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return [
        [min(latitudes), min(longitudes)],
        [max(latitudes), max(longitudes)],
    ]


def build_shell_map(
    counties_geojson: dict[str, Any] | None,
    selected_county: str,
    aoi_geometry: dict[str, Any] | None = None,
    draw_enabled: bool = True,
    preview_tiles: dict[str, str] | None = None,
    layer_compare_layers: dict[str, dict[str, str]] | None = None,
    layer_compare_left_id: str = "",
    layer_compare_right_id: str = "",
    layer_compare_active: bool = False,
    preview_scene_tile: str | None = None,
    analysis_layers: list[dict[str, Any]] | None = None,
    buffer_geometry: dict[str, Any] | None = None,
    osm_layers: dict[str, dict[str, Any]] | None = None,
    building_context_tile: str | None = None,
    focus_location: list[float] | None = None,
    map_center: list[float] | None = None,
    map_zoom: int | None = None,
    fit_bounds_requested: bool = True,
) -> folium.Map:
    selected_feature = (
        selected_county_feature(counties_geojson, selected_county)
        if counties_geojson
        else None
    )
    selected_bbox = feature_bbox(selected_feature) if selected_feature else None
    center = map_center or (
        bbox_center(selected_bbox) if selected_bbox else ROMANIA_CENTER
    )

    folium_map = folium.Map(
        location=center,
        zoom_start=map_zoom if map_zoom is not None else (8 if selected_feature else 6),
        tiles=None,
        control_scale=True,
        zoom_control=True,
    )
    folium.TileLayer(
        tiles="CartoDB positron",
        name="OSM Light / CartoDB Positron",
        overlay=False,
        control=True,
        show=True,
    ).add_to(folium_map)
    if building_context_tile:
        folium.TileLayer(
            tiles=building_context_tile,
            attr="MapTiler, OpenStreetMap contributors",
            name="Context cartografic MapTiler Streets",
            overlay=True,
            control=True,
            show=False,
            opacity=0.72,
        ).add_to(folium_map)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri, Maxar, Earthstar Geographics",
        name="Satelit / Esri World Imagery",
        overlay=False,
        control=True,
        show=False,
    ).add_to(folium_map)
    add_county_outlines(folium_map, counties_geojson, selected_county)
    add_aoi_layer(folium_map, aoi_geometry)
    if preview_scene_tile:
        folium.TileLayer(
            tiles=preview_scene_tile,
            attr="Google Earth Engine",
            name="Previzualizare scenă Sentinel-1",
            overlay=True,
            control=True,
            show=True,
        ).add_to(folium_map)
    add_tile_layers(folium_map, analysis_layers or [])
    add_buffer_layer(folium_map, buffer_geometry)
    add_osm_layers(folium_map, osm_layers or {})
    if draw_enabled:
        Draw(
            export=False,
            position="topleft",
            draw_options={
                "polyline": False,
                "polygon": {
                    "allowIntersection": False,
                    "showArea": True,
                    "shapeOptions": {
                        "color": "#16a34a",
                        "weight": 3,
                        "fillColor": "#22c55e",
                        "fillOpacity": 0.08,
                    },
                },
                "rectangle": {
                    "shapeOptions": {
                        "color": "#16a34a",
                        "weight": 3,
                        "fillColor": "#22c55e",
                        "fillOpacity": 0.08,
                    },
                },
                "circle": False,
                "marker": False,
                "circlemarker": False,
            },
            edit_options={"edit": False, "remove": False},
        ).add_to(folium_map)
    if selected_bbox and fit_bounds_requested:
        folium_map.fit_bounds(
            [[selected_bbox[1], selected_bbox[0]], [selected_bbox[3], selected_bbox[2]]]
        )
        NavigationControl(
            [[selected_bbox[1], selected_bbox[0]], [selected_bbox[3], selected_bbox[2]]],
            _geometry_bounds(aoi_geometry),
        ).add_to(folium_map)
    MeasureControl(
        position="topleft",
        primary_length_unit="meters",
        primary_area_unit="sqmeters",
    ).add_to(folium_map)
    Fullscreen(
        position="topleft",
        title="Ecran complet",
        title_cancel="Ieși din ecran complet",
    ).add_to(folium_map)
    folium.LatLngPopup().add_to(folium_map)
    ImpactLegend(
        legend_entries(
            analysis_layers,
            bool(buffer_geometry),
            osm_layers,
        )
    ).add_to(folium_map)
    if preview_tiles and preview_tiles.get("before") and preview_tiles.get("after"):
        SarSwipeControl(
            preview_tiles["before"],
            preview_tiles["after"],
        ).add_to(folium_map)
    elif layer_compare_layers:
        LayerCompareControl(
            layer_compare_layers,
            layer_compare_left_id,
            layer_compare_right_id,
            layer_compare_active,
        ).add_to(folium_map)
    if focus_location and len(focus_location) == 2:
        latitude, longitude = focus_location
        FocusLocation(latitude, longitude).add_to(folium_map)
    folium.LayerControl(collapsed=False, position="topright").add_to(folium_map)
    return folium_map

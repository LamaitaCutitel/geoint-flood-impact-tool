from __future__ import annotations

from src.impact_tool.map.builder import build_shell_map
from src.impact_tool.map.layers import add_osm_layers, add_tile_layers
from src.impact_tool.map.layers import _icon_kind
from src.impact_tool.models import ImpactToolState
from src.impact_tool.osm_impact import visible_impact_layers
from src.impact_tool.ui.shell import (
    _analysis_layers,
    _comparison_layers,
    _county_feature_from_click,
    _map_render_key,
)
import folium
import pytest


def test_map_contains_identify_measure_navigation_and_fullscreen() -> None:
    html = build_shell_map(None, "Galati").get_root().render()
    assert "LatLngPopup" in html or "latlng" in html.lower()
    assert "L.Control.Measure" in html
    assert "fullscreen" in html.lower()


def test_optional_maptiler_context_is_a_hidden_attributed_tile_layer() -> None:
    html = build_shell_map(
        None,
        "Galati",
        building_context_tile="https://tiles.example/{z}/{x}/{y}.png?key=test",
    ).get_root().render()
    assert "Context cartografic MapTiler Streets" in html
    assert "MapTiler, OpenStreetMap contributors" in html
    assert "FeatureCollection" not in html


def test_important_facility_icons_cover_normalized_categories() -> None:
    assert _icon_kind({"category": "hospital"}, "osm_critical") == "medical"
    assert _icon_kind({"category": "shelter"}, "osm_critical") == "shelter"
    assert _icon_kind({"category": "power_substation"}, "osm_critical") == "power"


def test_thematic_compare_tool_is_visible_and_has_presets() -> None:
    html = build_shell_map(
        None,
        "Galati",
        layer_compare_layers={
            "sar_water_before": {"name": "SAR BEFORE", "url": "https://tiles/before"},
            "sar_water_after": {"name": "SAR AFTER", "url": "https://tiles/after"},
        },
        layer_compare_left_id="sar_water_before",
        layer_compare_right_id="sar_water_after",
    ).get_root().render()
    assert "Compară layerele tematice" in html
    assert "SAR BEFORE ↔ SAR AFTER" in html
    assert "innerHTML = '↔'" in html
    assert "Inversează stânga / dreapta" in html
    assert "var previousLeft = left.value" in html
    assert "tileerror" in html


def test_only_one_compare_divider_can_be_active() -> None:
    html = build_shell_map(
        None,
        "Galati",
        preview_tiles={"before": "https://tiles/before", "after": "https://tiles/after"},
        layer_compare_layers={
            "sar_water_before": {"name": "SAR BEFORE", "url": "https://tiles/before"},
            "sar_water_after": {"name": "SAR AFTER", "url": "https://tiles/after"},
        },
        layer_compare_active=True,
    ).get_root().render()
    assert "LayerCompareControl" not in html
    assert html.count("map.createPane('impactSwipeBefore')") == 1
    assert "L.control.sideBySide(" not in html


def test_compare_rejects_invalid_tile_urls_and_excludes_osm() -> None:
    html = build_shell_map(
        None,
        "Galati",
        layer_compare_layers={
            "sar_new_water": {"name": "SAR", "url": "invalid"},
        },
        layer_compare_left_id="sar_new_water",
        layer_compare_right_id="sar_new_water",
        layer_compare_active=True,
    ).get_root().render()
    assert "URL de tile valid" in html
    assert "osm_buildings" not in html


def test_comparison_layers_include_required_basemaps_and_products() -> None:
    state = ImpactToolState(
        analysis_results={
            "sar": {
                "tiles": {
                    "sar_water_before": "before",
                    "sar_water_after": "after",
                    "sar_new_water": "new",
                }
            },
            "dynamic_world": {
                "tiles": {
                    key: {"url": key, "status": "reușit"}
                    for key in (
                        "dynamic_world_before",
                        "dynamic_world_after",
                        "dynamic_world_changes",
                        "dynamic_world_new_water",
                        "both_methods",
                        "only_sar",
                        "only_dynamic_world",
                    )
                }
            },
        }
    )
    layers = _comparison_layers(state)
    assert {
        "sar_water_before",
        "sar_water_after",
        "sar_new_water",
        "dynamic_world_before",
        "dynamic_world_after",
        "dynamic_world_changes",
        "dynamic_world_new_water",
        "both_methods",
        "only_sar",
        "only_dynamic_world",
        "basemap_satellite",
        "basemap_osm_light",
    }.issubset(layers)


def test_layer_control_contains_only_two_basemaps() -> None:
    html = build_shell_map(
        None,
        "Galati",
        analysis_layers=[
            {
                "id": "sar_new_water",
                "name": "Apa noua SAR",
                "tile_url": "https://tiles.test/{z}/{x}/{y}",
                "shown": True,
            }
        ],
    ).get_root().render()
    assert html.count("L.control.layers(") == 1
    assert "OSM Light / CartoDB Positron" in html
    assert "Satelit / Esri World Imagery" in html
    control_config = html.split("L.control.layers(", 1)[1].split(");", 1)[0]
    assert "Apa noua SAR" not in control_config


def test_active_tile_layer_is_visible_even_when_not_shown_by_default() -> None:
    folium_map = folium.Map(location=[45.5, 27.5])
    add_tile_layers(
        folium_map,
        [
            {
                "id": "dynamic_world_before",
                "name": "Dynamic World BEFORE",
                "tile_url": "https://tiles.test/{z}/{x}/{y}",
                "shown": False,
            }
        ],
    )
    html = folium_map.get_root().render()
    assert "Dynamic World BEFORE" not in html
    assert "https://tiles.test/{z}/{x}/{y}" in html


def test_active_tile_layer_without_url_emits_warning() -> None:
    folium_map = folium.Map(location=[45.5, 27.5])
    with pytest.warns(UserWarning, match="nu are tile_url"):
        add_tile_layers(
            folium_map,
            [{"id": "sar_new_water", "name": "Apa noua SAR", "shown": True}],
        )


def test_navigation_control_can_center_aoi() -> None:
    counties = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"NAME_LATN": "Galati"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[27, 45], [28, 45], [28, 46], [27, 46], [27, 45]]
                    ],
                },
            }
        ],
    }
    aoi = {
        "type": "Polygon",
        "coordinates": [
            [[27.2, 45.2], [27.4, 45.2], [27.4, 45.4], [27.2, 45.4], [27.2, 45.2]]
        ],
    }
    html = build_shell_map(counties, "Galati", aoi_geometry=aoi).get_root().render()
    assert "Centrează pe AOI" in html


def test_focus_uses_single_set_view_at_zoom_17() -> None:
    html = build_shell_map(
        None,
        "Galati",
        focus_location=[45.5, 27.5],
    ).get_root().render()
    assert html.count("setView([45.5, 27.5], 17)") == 1


def test_map_render_key_ignores_leaflet_visibility_and_tracks_real_changes() -> None:
    state = ImpactToolState(active_area_hash="area")
    initial = _map_render_key(state)
    state.buffer_meters = 500
    changed_buffer = _map_render_key(state)
    state.osm_filters["roads"] = False
    changed_filter = _map_render_key(state)
    changed_focus = _map_render_key(state, [45.5, 27.5])
    assert initial != changed_buffer
    assert changed_buffer == changed_filter
    assert changed_filter != changed_focus


def test_critical_mode_filters_secondary_layers() -> None:
    impact = {
        "layers": {
            key: {"type": "FeatureCollection", "features": []}
            for key in (
                "osm_buildings",
                "osm_roads",
                "osm_railways",
                "osm_bridges",
                "osm_critical",
            )
        }
    }
    visible = visible_impact_layers(
        impact,
        {key: True for key in ("buildings", "roads", "railways", "bridges", "critical")},
        critical_only=True,
    )
    assert set(visible) == {"osm_roads", "osm_bridges", "osm_critical"}


def test_osm_filters_can_disable_category() -> None:
    impact = {
        "layers": {
            "osm_roads": {"type": "FeatureCollection", "features": []},
            "osm_critical": {"type": "FeatureCollection", "features": []},
        }
    }
    visible = visible_impact_layers(
        impact,
        {"roads": False, "critical": True},
        critical_only=False,
    )
    assert set(visible) == {"osm_critical"}


def test_empty_osm_layer_does_not_build_invalid_tooltip() -> None:
    folium_map = folium.Map(location=[45.5, 27.5])
    add_osm_layers(
        folium_map,
        {
            "osm_roads": {
                "type": "FeatureCollection",
                "display_name": "Drumuri",
                "features": [],
            }
        },
    )
    assert "Drumuri" not in folium_map.get_root().render()


def test_osm_tooltip_uses_only_fields_available_on_all_features() -> None:
    folium_map = folium.Map(location=[45.5, 27.5])
    add_osm_layers(
        folium_map,
        {
            "osm_roads": {
                "type": "FeatureCollection",
                "display_name": "Drumuri",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[27.4, 45.4], [27.5, 45.5]],
                        },
                        "properties": {"status": "Intersectat direct"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[27.5, 45.5], [27.6, 45.6]],
                        },
                        "properties": {
                            "name": "DN test",
                            "status": "În buffer de avertizare",
                        },
                    },
                ],
            }
        },
    )
    html = folium_map.get_root().render()
    assert "Status" in html
    assert "Distanță până la apă" not in html


def test_all_analysis_layers_are_sent_to_leaflet_control() -> None:
    state = ImpactToolState(
        active_layers=["sar_new_water"],
        analysis_results={
            "sar": {
                "tiles": {
                    "sar_water_before": "https://tiles/before",
                    "sar_water_after": "https://tiles/after",
                    "sar_new_water": "https://tiles/new-water",
                }
            }
        },
    )
    layers = _analysis_layers(state)
    assert [layer["id"] for layer in layers] == [
        "sar_water_before",
        "sar_water_after",
        "sar_new_water",
    ]


def test_county_click_resolves_feature_for_selection_and_zoom() -> None:
    counties = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"NAME_LATN": "Galați"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[27, 45], [28, 45], [28, 46], [27, 46], [27, 45]]
                    ],
                },
            }
        ],
    }
    selected = _county_feature_from_click(counties, "Galați")
    assert selected is counties["features"][0]
    assert _county_feature_from_click(counties, "Brăila") is None


def test_streamlit_layer_filters_are_removed() -> None:
    from pathlib import Path

    source = Path("src/impact_tool/ui/shell.py").read_text(encoding="utf-8")
    assert "_render_layer_controls" not in source
    assert "_render_osm_map_filters" not in source


def test_leaflet_receives_layers_independent_of_legacy_active_layers() -> None:
    state = ImpactToolState(
        active_layers=[],
        analysis_results={
            "sar": {
                "tiles": {
                    "sar_water_before": "https://tiles/before",
                    "sar_water_after": "https://tiles/after",
                    "sar_new_water": "https://tiles/new-water",
                }
            },
            "dynamic_world": {
                "tiles": {
                    "dynamic_world_before": "https://tiles/dw-before",
                }
            },
        },
    )
    assert _analysis_layers(state)


def test_critical_asset_has_one_clustered_svg_marker() -> None:
    folium_map = folium.Map(location=[45.5, 27.5])
    add_osm_layers(
        folium_map,
        {
            "osm_critical": {
                "type": "FeatureCollection",
                "display_name": "Obiective",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [27.5, 45.5]},
                        "properties": {
                            "name": "Spital",
                            "amenity": "hospital",
                            "status": "Intersectat direct",
                        },
                    }
                ],
            }
        },
    )
    html = folium_map.get_root().render()
    assert html.count("L.marker(") == 1
    assert "markerClusterGroup" in html
    assert "svg xmlns=" in html
    assert "Categorie:" in html
    assert "Distanță până la apă:" in html
    assert "Sursă: OpenStreetMap" in html


def test_bridge_has_line_and_centroid_icon() -> None:
    folium_map = folium.Map(location=[45.5, 27.5])
    add_osm_layers(
        folium_map,
        {
            "osm_bridges": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[27.4, 45.4], [27.6, 45.6]],
                        },
                        "properties": {"status": "În buffer de avertizare"},
                    }
                ],
            }
        },
    )
    html = folium_map.get_root().render()
    assert "LineString" in html
    assert html.count("L.marker(") == 1
    assert 'd=\\"M4 20h22v4H4' in html
    assert "<text" not in html


def test_reference_buildings_render_only_at_large_zoom() -> None:
    folium_map = folium.Map(location=[45.5, 27.5], zoom_start=10)
    add_osm_layers(
        folium_map,
        {
            "osm_buildings": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [27.5, 45.5]},
                        "properties": {"status": "Referință"},
                    }
                ],
            }
        },
    )
    html = folium_map.get_root().render()
    assert "syncReferenceVisibility" in html
    assert "getZoom() >= 14" in html


def test_osm_layers_ignore_legacy_streamlit_visibility_state() -> None:
    from src.impact_tool.ui.shell import _visible_osm_layers

    state = ImpactToolState(
        active_layers=["osm_buildings", "osm_critical"],
        presentation_mode=True,
        osm_filters={
            "buildings": True,
            "critical": True,
            "reference_buildings": False,
        },
        analysis_results={
            "osm_impact": {
                "layers": {
                    "osm_buildings": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "properties": {
                                    "status": "Referință",
                                    "infrastructure_level": "context tehnic",
                                }
                            }
                        ],
                    },
                    "osm_critical": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "properties": {
                                    "status": "Intersectat direct",
                                    "infrastructure_level": "esențial",
                                }
                            }
                        ],
                    },
                }
            }
        },
    )
    visible = _visible_osm_layers(state)
    assert len(visible["osm_buildings"]["features"]) == 1
    assert len(visible["osm_critical"]["features"]) == 1


def test_osm_ui_contains_zoom_completeness_and_hidden_qa() -> None:
    from pathlib import Path

    results_source = Path("src/impact_tool/ui/results.py").read_text(encoding="utf-8")
    shell_source = Path("src/impact_tool/ui/shell.py").read_text(encoding="utf-8")
    assert "_render_osm_map_filters" not in shell_source
    assert "Centrează elementul selectat" in results_source
    assert 'button("Zoom"' not in results_source
    assert "completitudine" in results_source
    assert 'expander("Mod QA", expanded=False)' in results_source

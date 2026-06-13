from __future__ import annotations

from src.impact_tool.map.legend import legend_entries


def test_legend_contains_only_shown_rasters_and_compact_osm_statuses() -> None:
    entries = legend_entries(
        [
            {
                "id": "sar_new_water",
                "name": "Apă nouă evidențiată prin SAR",
                "color": "#22d3ee",
                "shown": False,
            },
            {
                "id": "dynamic_world_new_water",
                "name": "Apă nouă evidențiată prin Dynamic World",
                "color": "#0284c7",
                "shown": False,
            },
        ],
        True,
        {
            "osm_buildings": {"features": [{}]},
            "osm_roads": {"features": [{}]},
            "osm_railways": {"features": [{}]},
            "osm_bridges": {"features": [{}]},
            "osm_critical": {"features": [{}]},
        },
    )
    labels = {label for label, _ in entries}
    assert "Apă nouă evidențiată prin SAR" not in labels
    assert "Apă nouă evidențiată prin Dynamic World" not in labels
    assert "Buffer de avertizare" in labels
    assert "Intersectat direct" in labels
    assert "În buffer de avertizare" in labels
    assert "Reper neexpus" in labels

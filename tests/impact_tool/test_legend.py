from __future__ import annotations

from src.impact_tool.map.legend import legend_entries


def test_legend_contains_only_active_raster_layers_and_detailed_osm_entries() -> None:
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
    assert "Apă nouă evidențiată prin SAR" in labels
    assert "Apă nouă evidențiată prin Dynamic World" in labels
    assert "Buffer de avertizare" in labels
    assert "Clădiri intersectate direct" in labels
    assert "Clădiri în buffer" in labels
    assert "Clădiri de referință" in labels
    assert "Drumuri intersectate direct" in labels
    assert "Căi ferate intersectate direct" in labels
    assert "Poduri intersectate direct" in labels
    assert "Obiective critice intersectate direct" in labels

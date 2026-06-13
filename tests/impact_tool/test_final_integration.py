from __future__ import annotations

from io import BytesIO

from streamlit.testing.v1 import AppTest

from src.impact_tool import analysis
from src.impact_tool.cache import PersistentCache
from src.impact_tool.dynamic_world import _mandatory_tiles_ready
from src.impact_tool.map.builder import build_shell_map
from src.impact_tool.models import ImpactToolState
from src.impact_tool.osm import load_osm_categories
from src.impact_tool.osm_impact import classify_osm_impact
from src.impact_tool.report import generate_report_pdf
from src.impact_tool.scenes import hydrate_scene_thumbnails
from src.impact_tool.state import set_aoi, update_buffer


COUNTY = {
    "type": "Polygon",
    "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 46], [27, 45]]],
}
AOI = {
    "type": "Polygon",
    "coordinates": [[[27.2, 45.2], [27.4, 45.2], [27.4, 45.4], [27.2, 45.2]]],
}


class FakeGeeStatus:
    available = True
    ee = object()
    message = "ok"


class FakeThumbnailImage:
    def getThumbURL(self, parameters):
        return "https://example.test/thumbnail.png"


def test_final_offline_galati_workflow(tmp_path, monkeypatch) -> None:
    cache = PersistentCache(tmp_path)
    fetch_calls = []

    def fetcher(query):
        fetch_calls.append(query)
        return {"elements": []}

    first = load_osm_categories(
        analysis_complete=True,
        aoi_hash="galati",
        bbox=[27, 45, 28, 46],
        geometry=COUNTY,
        cache=cache,
        fetcher=fetcher,
    )
    first_call_count = len(fetch_calls)
    second = load_osm_categories(
        analysis_complete=True,
        aoi_hash="galati",
        bbox=[27, 45, 28, 46],
        geometry=COUNTY,
        cache=cache,
        fetcher=fetcher,
    )
    assert first_call_count == 5
    assert len(fetch_calls) == first_call_count
    assert all(status["source"] == "cache" for status in second["status"].values())
    assert first["cache_refs"] == second["cache_refs"]

    state = ImpactToolState(
        county_geometry=COUNTY,
        county_bbox=[27, 45, 28, 46],
        active_area_hash="galati",
        active_area_bbox=[27, 45, 28, 46],
    )
    assert set_aoi(state, AOI)
    for buffer_meters in (1, 250, 1000):
        update_buffer(state, buffer_meters)
        assert state.buffer_meters == buffer_meters

    monkeypatch.setattr(
        "src.impact_tool.scenes.selected_scene_image",
        lambda *args: FakeThumbnailImage(),
    )
    monkeypatch.setattr(
        "src.impact_tool.scenes.urlopen",
        lambda *args, **kwargs: BytesIO(b"png"),
    )
    scenes, _ = hydrate_scene_thumbnails(
        cache=cache,
        ee=object(),
        aoi=object(),
        aoi_hash="galati",
        scenes=[
            {
                "ee_id": "before",
                "acquisition_time": "2024-09-01T10:00:00Z",
                "polarizations": ["VH"],
                "orbit_pass": "ASCENDING",
            },
            {
                "ee_id": "after",
                "acquisition_time": "2024-09-14T10:00:00Z",
                "polarizations": ["VH"],
                "orbit_pass": "ASCENDING",
            },
        ],
    )
    assert all(scene["thumbnail_url"] for scene in scenes)

    scene_html = build_shell_map(
        None,
        "Galati",
        preview_tiles={"before": "https://tiles/before", "after": "https://tiles/after"},
    ).get_root().render()
    result_html = build_shell_map(
        None,
        "Galati",
        layer_compare_layers={
            "sar_water_before": {"name": "SAR BEFORE", "url": "https://tiles/before"},
            "sar_water_after": {"name": "SAR AFTER", "url": "https://tiles/after"},
        },
    ).get_root().render()
    assert scene_html.count("map.createPane('impactSwipeBefore')") == 1
    assert "L.control.sideBySide(" not in scene_html
    assert "Compară layerele tematice" in result_html

    required_tiles = {
        key: {"status": "reușit", "url": key}
        for key in (
            "dynamic_world_before",
            "dynamic_world_after",
            "dynamic_world_new_water",
        )
    }
    assert _mandatory_tiles_ready(required_tiles, tuple(required_tiles))

    impact = classify_osm_impact(
        {
            "osm_buildings": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"osm_type": "way", "osm_id": 1},
                        "geometry": {"type": "Point", "coordinates": [27.5, 45.5]},
                    }
                ],
            }
        },
        {"type": "Point", "coordinates": [27.5, 45.5]},
        250,
    )
    assert impact["metrics"]["buildings_direct"] == 1

    report_state = ImpactToolState(
        county_name="Galati",
        county_geometry=COUNTY,
        active_area_km2=100,
        analysis_complete=True,
        analysis_hash="integration",
        before_scene={"acquisition_time": "2024-09-01T10:00:00Z"},
        after_scene={"acquisition_time": "2024-09-14T10:00:00Z"},
        analysis_results={
            "sar": {
                "metrics": {"sar_new_water_area_km2": 1.25},
                "new_water_geometry": {
                    "type": "Point",
                    "coordinates": [27.5, 45.5],
                },
            },
            "osm_impact": impact,
        },
    )
    assert generate_report_pdf(report_state).startswith(b"%PDF")


def test_rapid_and_detailed_modes_and_streamlit_restart(monkeypatch) -> None:
    monkeypatch.setattr(analysis, "initialize_earth_engine", lambda: FakeGeeStatus())
    monkeypatch.setattr(analysis, "build_aoi_from_geometry", lambda *args: "aoi")
    monkeypatch.setattr(
        analysis,
        "run_sar_analysis",
        lambda *args: {
            "products": {"sar_new_water": "water"},
            "duration_seconds": 0.1,
            "vectorization_duration_seconds": 0.01,
        },
    )
    monkeypatch.setattr(
        analysis,
        "run_dynamic_world_analysis",
        lambda *args: {
            "status": "reușit",
            "metrics": {},
            "products": {},
        },
    )
    monkeypatch.setattr(analysis, "execute_osm_loading", lambda *args, **kwargs: True)

    for mode in ("rapid", "detaliat"):
        state = ImpactToolState(
            county_geometry=COUNTY,
            active_area_hash="galati",
            active_area_bbox=[27, 45, 28, 46],
            before_scene={"ee_id": "before"},
            after_scene={"ee_id": "after"},
            scenes_confirmed=True,
        )
        assert analysis.execute_analysis(state, mode=mode)
        assert state.analysis_complete

    for _ in range(2):
        app = AppTest.from_file("impact_tool.py")
        app.run(timeout=20)
        assert not app.exception

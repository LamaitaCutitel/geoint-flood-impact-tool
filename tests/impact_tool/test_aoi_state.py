from __future__ import annotations

from src.impact_tool.aoi import (
    area_metadata,
    geometry_from_drawing,
    validate_aoi,
)
from src.impact_tool.models import ImpactToolState
from src.impact_tool.state import (
    clear_aoi,
    reset_analysis_results,
    reset_area_dependent_state,
    reset_scene_selection,
    set_aoi,
    set_county,
)


COUNTY = {
    "type": "Polygon",
    "coordinates": [[
        [27.0, 45.0],
        [28.0, 45.0],
        [28.0, 46.0],
        [27.0, 46.0],
        [27.0, 45.0],
    ]],
}

AOI = {
    "type": "Polygon",
    "coordinates": [[
        [27.2, 45.2],
        [27.4, 45.2],
        [27.4, 45.4],
        [27.2, 45.4],
        [27.2, 45.2],
    ]],
}


def _state() -> ImpactToolState:
    state = ImpactToolState()
    set_county(state, "Galati", COUNTY, [27.0, 45.0, 28.0, 46.0])
    return state


def test_county_without_aoi_uses_exact_county_geometry():
    state = _state()

    assert state.active_geometry == COUNTY
    assert state.aoi_active is False
    assert state.active_area_bbox == [27.0, 45.0, 28.0, 46.0]
    assert state.active_area_km2 > 0
    assert state.active_area_hash


def test_valid_aoi_becomes_active_area():
    state = _state()

    assert set_aoi(state, AOI) is True
    assert state.active_geometry == AOI
    assert state.aoi_active is True
    assert state.active_area_bbox == [27.2, 45.2, 27.4, 45.4]
    assert state.active_area_centroid == [27.3, 45.3]


def test_clear_aoi_returns_to_county():
    state = _state()
    set_aoi(state, AOI)

    assert clear_aoi(state) is True
    assert state.aoi_geometry is None
    assert state.active_geometry == COUNTY
    assert state.active_area_bbox == [27.0, 45.0, 28.0, 46.0]


def test_invalid_and_empty_aoi_are_rejected():
    empty = validate_aoi(None, COUNTY)
    invalid = validate_aoi(
        {"type": "Point", "coordinates": [27.2, 45.2]},
        COUNTY,
    )

    assert empty.valid is False
    assert "gol" in empty.errors[0]
    assert invalid.valid is False
    assert "poligon" in invalid.errors[0]


def test_aoi_outside_county_is_rejected():
    outside = {
        "type": "Polygon",
        "coordinates": [[
            [30.0, 48.0],
            [30.2, 48.0],
            [30.2, 48.2],
            [30.0, 48.2],
            [30.0, 48.0],
        ]],
    }

    validation = validate_aoi(outside, COUNTY)

    assert validation.valid is False
    assert "nu intersectează" in validation.errors[0]


def test_large_aoi_produces_warning():
    validation = validate_aoi(COUNTY, COUNTY)

    assert validation.valid is True
    assert any("mare parte" in warning for warning in validation.warnings)


def test_large_aoi_covering_county_is_detected_and_clipped_without_internal_vertices():
    covering = {
        "type": "Polygon",
        "coordinates": [[
            [26.0, 44.0],
            [29.0, 44.0],
            [29.0, 47.0],
            [26.0, 47.0],
            [26.0, 44.0],
        ]],
    }
    validation = validate_aoi(covering, COUNTY)
    assert validation.valid is True
    assert validation.geometry is not None
    assert area_metadata(validation.geometry).bbox == [27.0, 45.0, 28.0, 46.0]
    assert any("decupat" in warning for warning in validation.warnings)


def test_partially_overlapping_aoi_is_clipped_to_exact_intersection():
    partial = {
        "type": "Polygon",
        "coordinates": [[
            [27.5, 45.5],
            [28.5, 45.5],
            [28.5, 46.5],
            [27.5, 46.5],
            [27.5, 45.5],
        ]],
    }
    validation = validate_aoi(partial, COUNTY)
    assert validation.valid is True
    assert validation.geometry is not None
    assert area_metadata(validation.geometry).bbox == [27.5, 45.5, 28.0, 46.0]


def test_geometry_from_streamlit_drawing_feature():
    drawing = {"type": "Feature", "properties": {}, "geometry": AOI}

    assert geometry_from_drawing(drawing) == AOI


def test_area_metadata_is_stable():
    first = area_metadata(AOI)
    second = area_metadata(AOI)

    assert first.area_hash == second.area_hash
    assert first.centroid == [27.3, 45.3]
    assert first.area_km2 > 0


def test_selective_resets_keep_reusable_cache():
    state = _state()
    state.before_scene = {"id": "before"}
    state.after_scene = {"id": "after"}
    state.scenes_confirmed = True
    state.analysis_complete = True
    state.analysis_results = {"area": 1.0}
    state.active_layers = ["sar_new_water"]
    state.reusable_cache = {"sentinel1:query": {"scenes": []}}

    reset_area_dependent_state(state)

    assert state.before_scene is None
    assert state.after_scene is None
    assert state.analysis_results == {}
    assert state.active_layers == ["sar_new_water", "buffer", "osm_critical"]
    assert state.reusable_cache == {"sentinel1:query": {"scenes": []}}


def test_county_change_clears_aoi_scenes_and_results():
    state = _state()
    set_aoi(state, AOI)
    state.before_scene = {"id": "before"}
    state.analysis_complete = True
    state.reusable_cache = {"keep": True}

    changed = set_county(
        state,
        "Braila",
        COUNTY,
        [27.0, 45.0, 28.0, 46.0],
    )

    assert changed is True
    assert state.aoi_geometry is None
    assert state.before_scene is None
    assert state.analysis_complete is False
    assert state.reusable_cache == {"keep": True}


def test_individual_reset_functions_are_scoped():
    state = _state()
    state.before_scene = {"id": "before"}
    state.scene_candidates = [{"ee_id": "old"}]
    state.scene_query = {"start_date": "2024-01-01"}
    state.scene_errors = ["old"]
    state.scene_warnings = ["old"]
    state.swipe_enabled = True
    state.preview_tiles = {"before": "tile"}
    state.scene_compare_active = True
    state.scene_compare_tiles = {"before": "tile"}
    state.layer_compare_active = True
    state.report_bytes = b"pdf"
    state.report_filename = "old.pdf"
    state.analysis_results = {"result": True}
    state.analysis_complete = True

    reset_scene_selection(state)
    assert state.before_scene is None
    assert state.scene_candidates == []
    assert state.scene_query == {}
    assert state.scene_errors == []
    assert state.scene_warnings == []
    assert state.swipe_enabled is False
    assert state.preview_tiles == {}
    assert state.scene_compare_active is False
    assert state.scene_compare_tiles == {}
    assert state.layer_compare_active is False
    assert state.report_bytes is None
    assert state.report_filename == ""
    assert state.analysis_results == {"result": True}

    reset_analysis_results(state)
    assert state.analysis_results == {}
    assert state.analysis_complete is False

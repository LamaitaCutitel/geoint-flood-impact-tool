from __future__ import annotations

from datetime import date

from src.impact_tool.models import ImpactToolState
from src.impact_tool.presets import (
    GALATI_EVENT_DATE,
    GALATI_PRESET_NAME,
    apply_galati_preset,
)
from src.impact_tool.state import initialize_state, update_buffer


COUNTY = {
    "type": "Polygon",
    "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 46], [27, 45]]],
}


def test_galati_preset_populates_demo_values_and_cache_status(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.impact_tool.presets.inspect_osm_cache",
        lambda *args, **kwargs: {
            category: {"status": "valid"}
            for category in ("buildings", "roads", "railways", "bridges", "critical")
        },
    )
    state = ImpactToolState(
        county_name="Galati",
        county_geometry=COUNTY,
        county_bbox=[27, 45, 28, 46],
        aoi_geometry={
            "type": "Polygon",
            "coordinates": [[[27.2, 45.2], [27.3, 45.2], [27.3, 45.3], [27.2, 45.2]]],
        },
        buffer_meters=1000,
    )
    session = {}
    apply_galati_preset(state, session, COUNTY, [27, 45, 28, 46])
    assert state.county_name == "Galati"
    assert state.preset_name == GALATI_PRESET_NAME
    assert state.event_date == GALATI_EVENT_DATE
    assert state.buffer_meters == 250
    assert state.aoi_geometry is None
    assert session["impact_scene_start_preset"] == date(2024, 9, 1)
    assert session["impact_scene_end_preset"] == date(2024, 9, 30)
    assert session["impact_scene_polarization_preset"] == "VH"
    assert "Cache Galați pregătit pentru rulare rapidă" in state.cache_events
    assert all(
        status["status"] == "valid"
        for status in state.preset_cache_status.values()
    )


def test_buffer_extremes_and_restart_preserve_state() -> None:
    session = {}
    state = initialize_state(session)
    for value in (1, 250, 1000):
        update_buffer(state, value)
        assert state.buffer_meters == value
    assert initialize_state(session) is state

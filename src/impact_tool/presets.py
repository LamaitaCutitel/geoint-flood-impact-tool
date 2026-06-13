from __future__ import annotations

from datetime import date
from typing import Any, MutableMapping

from src.impact_tool.cache import PersistentCache
from src.impact_tool.models import ImpactToolState
from src.impact_tool.osm import inspect_osm_cache
from src.impact_tool.osm_impact import buffered_geometry
from src.impact_tool.state import clear_aoi, set_county, update_buffer


GALATI_PRESET_NAME = "Inundații Galați — septembrie 2024"
GALATI_EVENT_DATE = "2024-09-14"


def apply_galati_preset(
    state: ImpactToolState,
    session_state: MutableMapping[str, Any],
    county_geometry: dict[str, Any],
    county_bbox: list[float],
) -> None:
    clear_aoi(state)
    set_county(state, "Galati", county_geometry, county_bbox)
    update_buffer(state, 250)
    state.preset_name = GALATI_PRESET_NAME
    state.event_date = GALATI_EVENT_DATE
    session_state["impact_scene_start_preset"] = date(2024, 9, 1)
    session_state["impact_scene_end_preset"] = date(2024, 9, 30)
    session_state["impact_scene_polarization_preset"] = "VH"
    query_geometry, _ = buffered_geometry(county_geometry, 1000)
    state.preset_cache_status = inspect_osm_cache(
        PersistentCache(),
        query_geometry,
        analysis_mode="rapid",
    )
    statuses = {
        item.get("status", "lipsă")
        for item in state.preset_cache_status.values()
    }
    if statuses == {"valid"}:
        state.cache_events.append("Cache Galați pregătit pentru rulare rapidă")
    else:
        state.cache_events.append(
            "Cache Galați indisponibil sau incomplet: "
            + ", ".join(sorted(statuses or {"lipsă"}))
        )

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import asdict
from typing import Any

from src.impact_tool.aoi import area_metadata, validate_aoi
from src.impact_tool.models import ImpactToolState


STATE_KEY = "impact_tool_state"


def initialize_state(session_state: MutableMapping[str, Any]) -> ImpactToolState:
    current = session_state.get(STATE_KEY)
    if isinstance(current, ImpactToolState):
        _migrate_sar_parameters(current)
        return current
    state = ImpactToolState()
    session_state[STATE_KEY] = state
    return state


def _migrate_sar_parameters(state: ImpactToolState) -> None:
    legacy_scale = state.analysis_parameters.pop("scale_meters", 10)
    defaults = {
        "analysis_scale_meters": legacy_scale,
        "vectorization_scale_meters": 30,
        "minimum_polygon_area_m2": 1000,
        "geometry_simplification_tolerance_m": 10,
    }
    for key, value in defaults.items():
        state.analysis_parameters.setdefault(key, value)


def state_snapshot(state: ImpactToolState) -> dict[str, Any]:
    return asdict(state)


def record_timing(state: ImpactToolState, stage: str, seconds: float) -> None:
    duration = round(max(0.0, float(seconds)), 3)
    state.timings[stage] = duration
    state.cache_events.append(f"Timp {stage}: {duration:.3f} s.")


def invalidate_report(state: ImpactToolState) -> None:
    state.report_bytes = None
    state.report_filename = ""
    state.report_requested = False


def reset_comparison(state: ImpactToolState) -> None:
    state.comparison_ready = False
    state.swipe_enabled = False
    state.preview_tiles.clear()
    state.scene_compare_active = False
    state.scene_compare_tiles.clear()
    state.layer_compare_active = False
    state.preview_scene_id = ""
    state.preview_scene_tile = ""


def reset_scene_selection(state: ImpactToolState) -> None:
    state.before_scene = None
    state.after_scene = None
    state.scene_candidates.clear()
    state.scene_query.clear()
    state.scene_errors.clear()
    state.scene_warnings.clear()
    state.scene_gallery_limit = 8
    state.scene_current_id = ""
    state.scenes_confirmed = False
    state.scene_pair_validation.clear()
    state.relative_orbit_override = False
    state.low_coverage_override = False
    reset_comparison(state)
    invalidate_report(state)
    state.cache_events.append("Selecția scenelor a fost resetată.")


def reset_analysis_results(state: ImpactToolState) -> None:
    state.analysis_complete = False
    state.analysis_results.clear()
    state.osm_status.clear()
    state.osm_cache_refs.clear()
    state.active_layers = ["sar_new_water", "buffer", "osm_critical"]
    state.analysis_hash = ""
    invalidate_report(state)
    state.analysis_progress = 0
    state.timings.clear()
    state.analysis_stage = "Pregătit pentru analiză"
    state.map_data_revision += 1


def reset_area_dependent_state(state: ImpactToolState) -> None:
    reset_scene_selection(state)
    reset_analysis_results(state)
    state.cache_events.append("Cache-ul dependent de aria activă trebuie revalidat.")


def update_buffer(state: ImpactToolState, buffer_meters: int) -> bool:
    if buffer_meters == state.buffer_meters:
        return False
    state.buffer_meters = buffer_meters
    state.analysis_results.pop("osm_impact", None)
    state.osm_impact_available = False
    invalidate_report(state)
    state.cache_events.append(
        f"Se recalculează impactul pentru bufferul de {buffer_meters} m."
    )
    return True


def update_sar_parameters(state: ImpactToolState, **parameters: Any) -> bool:
    supported = {
        "water_threshold",
        "smoothing_meters",
        "minimum_connected_pixels",
        "analysis_scale_meters",
        "vectorization_scale_meters",
        "minimum_polygon_area_m2",
        "geometry_simplification_tolerance_m",
    }
    updates = {
        key: value
        for key, value in parameters.items()
        if key in supported and state.analysis_parameters.get(key) != value
    }
    if not updates:
        return False
    state.analysis_parameters.update(updates)
    reset_analysis_results(state)
    state.layer_compare_active = False
    state.sar_parameters_message = (
        "Parametrii SAR s-au schimbat. Rulează din nou analiza."
    )
    state.cache_events.append(state.sar_parameters_message)
    return True


def apply_scene_pair(
    state: ImpactToolState,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    confirmed: bool,
) -> None:
    changed = (
        (state.before_scene or {}).get("ee_id") != (before or {}).get("ee_id")
        or (state.after_scene or {}).get("ee_id") != (after or {}).get("ee_id")
    )
    if changed:
        reset_comparison(state)
        reset_analysis_results(state)
    state.before_scene = before
    state.after_scene = after
    state.scenes_confirmed = confirmed
    state.comparison_ready = bool(before and after and not confirmed)
    if confirmed:
        reset_comparison(state)
    if changed:
        state.cache_events.append("Scenele s-au schimbat; rezultatele dependente au fost invalidate.")


def set_county(
    state: ImpactToolState,
    county_name: str,
    county_geometry: dict | None,
    county_bbox: list[float],
) -> bool:
    changed = county_name != state.county_name
    state.county_name = county_name
    state.county_geometry = county_geometry
    state.county_bbox = list(county_bbox)
    if changed:
        state.aoi_geometry = None
        state.draw_requested = False
        state.area_warnings.clear()
        state.area_errors.clear()
        reset_area_dependent_state(state)
        state.map_fit_bounds_requested = True
    _set_active_area_metadata(state, state.active_geometry)
    return changed


def set_aoi(state: ImpactToolState, geometry: dict | None) -> bool:
    validation = validate_aoi(geometry, state.county_geometry)
    state.area_errors = validation.errors
    state.area_warnings = validation.warnings
    if not validation.valid or not validation.geometry:
        return False
    metadata = area_metadata(validation.geometry, validation.warnings)
    if metadata.area_hash == state.active_area_hash and state.aoi_geometry is not None:
        return False
    state.aoi_geometry = metadata.geometry
    state.draw_requested = False
    reset_area_dependent_state(state)
    state.map_fit_bounds_requested = True
    _apply_metadata(state, metadata)
    return True


def clear_aoi(state: ImpactToolState) -> bool:
    if state.aoi_geometry is None:
        return False
    state.aoi_geometry = None
    state.draw_requested = False
    state.area_warnings.clear()
    state.area_errors.clear()
    reset_area_dependent_state(state)
    state.map_fit_bounds_requested = True
    _set_active_area_metadata(state, state.county_geometry)
    return True


def _set_active_area_metadata(
    state: ImpactToolState,
    geometry: dict | None,
) -> None:
    if not geometry:
        state.active_area_bbox = []
        state.active_area_centroid = []
        state.active_area_km2 = 0.0
        state.active_area_hash = ""
        return
    _apply_metadata(state, area_metadata(geometry, state.area_warnings))


def _apply_metadata(state: ImpactToolState, metadata: Any) -> None:
    state.active_area_bbox = list(metadata.bbox)
    state.active_area_centroid = list(metadata.centroid)
    state.active_area_km2 = metadata.area_km2
    state.active_area_hash = metadata.area_hash
    state.area_warnings = list(metadata.warnings)

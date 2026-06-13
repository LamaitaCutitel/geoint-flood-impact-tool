from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import json
from time import perf_counter
from typing import Any

from src.gee.gee_auth import initialize_earth_engine
from src.gee.sentinel1_collection import build_aoi_from_geometry
from src.impact_tool.cache import analysis_hash
from src.impact_tool.dynamic_world import (
    correlate_osm_dynamic_world,
    run_dynamic_world_analysis,
)
from src.impact_tool.models import ImpactToolState
from src.app_support.osm_impact import build_osm_geojson_layers
from src.impact_tool.external.geoapify_places import fetch_important_facilities
from src.impact_tool.external.models import ExternalResult
from src.impact_tool.external.overpass_targeted import (
    fetch_targeted_impact,
    run_targeted_query,
)
from src.impact_tool.osm import build_category_query
from src.impact_tool.osm_impact import classify_osm_impact
from src.impact_tool.sar import SarParameters, run_sar_analysis
from src.impact_tool.sar_qa import run_sar_threshold_sweep
from src.impact_tool.state import invalidate_report, record_timing, reset_comparison


ProgressCallback = Callable[[int, str], None]


def execute_complete_analysis(
    state: ImpactToolState,
    progress_callback: ProgressCallback | None = None,
) -> bool:
    """Run the demonstrable workflow while preserving partial optional results."""

    def stage(percent: int, message: str) -> None:
        _progress(state, progress_callback, percent, message)

    sar_ok = execute_analysis(
        state,
        progress_callback=lambda percent, message: stage(
            min(50, max(5, int(percent * 0.5))),
            message,
        ),
        load_osm=False,
        mode=state.analysis_mode,
    )
    if not sar_ok:
        return False

    stage(55, "Analiză Dynamic World")
    dynamic_world_ok = execute_dynamic_world(state)
    if not dynamic_world_ok:
        state.cache_events.append(
            "Avertisment: Dynamic World este indisponibil; analiza SAR continuă."
        )

    stage(68, "Încărcare obiective importante")
    important_features_ok = execute_important_features(state)
    if not important_features_ok:
        state.cache_events.append(
            "Avertisment: obiectivele importante sunt indisponibile momentan."
        )

    stage(78, "Interogare OSM țintită și clasificare impact")
    osm_ok = execute_osm_loading(state, progress_callback=progress_callback)
    if not osm_ok:
        state.cache_events.append(
            "Avertisment: impactul OSM este indisponibil; rezultatele raster rămân active."
        )

    state.analysis_results["workflow_status"] = (
        "complet"
        if dynamic_world_ok and important_features_ok and osm_ok
        else "parțial"
    )
    stage(100, "Analiza completă s-a încheiat")
    return True


def execute_analysis(
    state: ImpactToolState,
    progress_callback: ProgressCallback | None = None,
    load_osm: bool = False,
    mode: str | None = None,
) -> bool:
    if not state.scenes_confirmed or not state.before_scene or not state.after_scene:
        state.analysis_error = "Confirmă imaginile BEFORE și AFTER înainte de analiză."
        return False
    state.analysis_running = True
    state.analysis_error = ""
    state.analysis_mode = mode or state.analysis_mode or "rapid"
    _progress(state, progress_callback, 5, "Inițializare Google Earth Engine")
    try:
        gee = initialize_earth_engine()
        if not gee.available or gee.ee is None:
            state.analysis_error = gee.message
            return False
        _progress(state, progress_callback, 15, "Pregătire arie activă și parametri SAR")
        aoi = build_aoi_from_geometry(gee.ee, state.active_geometry, state.active_area_bbox)
        parameters = SarParameters(**state.analysis_parameters)
        _progress(state, progress_callback, 25, "Calcul apă observată BEFORE și AFTER")
        sar = run_sar_analysis(
            gee.ee,
            aoi,
            state.before_scene,
            state.after_scene,
            parameters,
        )
        state.analysis_results["sar"] = sar
        state.analysis_results["sar_status"] = {
            "raster_available": any(
                (
                    item.get("status") == "reușit"
                    if isinstance(item, dict)
                    else bool(item)
                )
                for item in sar.get("tiles", {}).values()
            ),
            "metrics_available": bool(sar.get("metrics")) and all(
                (
                    item.get("status") == "reușit"
                    if isinstance(item, dict)
                    else item is not None
                )
                for item in sar.get("metrics", {}).values()
            ),
            "vectorization_available": (
                sar.get("vectorization", {}).get("status") == "reușit"
                or bool(sar.get("new_water_geometry"))
            ),
            "osm_impact_available": False,
        }
        state.sar_parameters_message = ""
        reset_comparison(state)
        record_timing(state, "SAR", sar.get("duration_seconds", 0))
        record_timing(
            state,
            "vectorizare",
            sar.get("vectorization_duration_seconds", 0),
        )
        state.preview_scene_id = ""
        state.preview_scene_tile = ""
        state.cache_events.append("Analiza SAR strict BEFORE / AFTER a fost finalizată.")
        _progress(state, progress_callback, 55, "Calcul apă nouă evidențiată prin SAR")

        state.analysis_hash = analysis_hash(
            state.active_area_hash,
            state.before_scene["ee_id"],
            state.after_scene["ee_id"],
            {**state.analysis_parameters, "analysis_mode": state.analysis_mode},
        )
        state.analysis_complete = True
        state.map_data_revision += 1
        state.active_layers = ["sar_new_water", "buffer"]
        state.osm_impact_available = False
        state.analysis_results["workflow_status"] = "sar_reușit"
        _progress(state, progress_callback, 100, "Analiza SAR a fost finalizată")
        return True
    except Exception as exc:
        state.analysis_error = f"Analiza SAR nu a putut fi finalizată: {exc}"
        _progress(
            state,
            progress_callback,
            state.analysis_progress,
            "Analiza s-a oprit cu eroare",
        )
        return False
    finally:
        state.analysis_running = False
        state.run_requested = False


def execute_dynamic_world(
    state: ImpactToolState,
    *,
    gee: Any | None = None,
    aoi: Any | None = None,
) -> bool:
    invalidate_report(state)
    sar = state.analysis_results.get("sar")
    if not sar or not state.before_scene or not state.after_scene:
        state.analysis_results["dynamic_world_error"] = (
            "Dynamic World necesită mai întâi o analiză SAR finalizată."
        )
        state.dynamic_world_requested = False
        return False
    started = perf_counter()
    try:
        gee_status = gee or initialize_earth_engine()
        if not gee_status.available or gee_status.ee is None:
            raise RuntimeError(gee_status.message)
        active_aoi = aoi or build_aoi_from_geometry(
            gee_status.ee,
            state.active_geometry,
            state.active_area_bbox,
        )
        result = run_dynamic_world_analysis(
            gee_status.ee,
            active_aoi,
            state.before_scene,
            state.after_scene,
            sar["products"]["sar_new_water"],
        )
        result["duration_seconds"] = round(perf_counter() - started, 3)
        result["source"] = "Google Dynamic World V1 prin Google Earth Engine"
        state.analysis_results["dynamic_world"] = result
        succeeded = result.get("status") == "reușit"
        if succeeded:
            state.map_data_revision += 1
            if "dynamic_world_new_water" not in state.active_layers:
                state.active_layers.append("dynamic_world_new_water")
            state.analysis_results.pop("dynamic_world_error", None)
        else:
            state.analysis_results["dynamic_world_error"] = (
                result.get("error") or result.get("status")
            )
            state.analysis_results["workflow_status"] = "parțial"
            state.cache_events.append(
                "Avertisment: Dynamic World este parțial sau indisponibil; "
                "rezultatul SAR rămâne disponibil."
            )
        impact = state.analysis_results.get("osm_impact")
        if succeeded and impact:
            state.analysis_results["osm_dynamic_world"] = correlate_osm_dynamic_world(
                gee_status.ee,
                result,
                impact,
            )
        if succeeded:
            state.cache_events.append(
                "Diferențele observate Dynamic World au fost calculate."
            )
        return succeeded
    except Exception as exc:
        state.analysis_results["dynamic_world_error"] = str(exc)
        state.analysis_results["workflow_status"] = "parțial"
        state.cache_events.append(
            "Dynamic World nu a putut fi calculat; rezultatul SAR rămâne disponibil."
        )
        return False
    finally:
        record_timing(state, "Dynamic World", perf_counter() - started)
        state.dynamic_world_requested = False


def execute_sar_qa(state: ImpactToolState) -> bool:
    invalidate_report(state)
    if not state.analysis_complete or not state.before_scene or not state.after_scene:
        state.analysis_results["sar_qa_error"] = (
            "Modul QA necesită mai întâi o analiză SAR finalizată."
        )
        state.sar_qa_requested = False
        return False
    started = perf_counter()
    try:
        gee_status = initialize_earth_engine()
        if not gee_status.available or gee_status.ee is None:
            raise RuntimeError(gee_status.message)
        aoi = build_aoi_from_geometry(
            gee_status.ee,
            state.active_geometry,
            state.active_area_bbox,
        )
        parameters = state.analysis_parameters
        result = run_sar_threshold_sweep(
            gee_status.ee,
            aoi,
            state.before_scene,
            state.after_scene,
            analysis_scale_meters=int(
                parameters.get("analysis_scale_meters", 10)
            ),
            smoothing_meters=int(parameters.get("smoothing_meters", 0)),
            minimum_connected_pixels=int(
                parameters.get("minimum_connected_pixels", 8)
            ),
            final_threshold=float(parameters.get("water_threshold", -18)),
        )
        state.analysis_results["sar_qa"] = result
        state.analysis_results.pop("sar_qa_error", None)
        state.cache_events.append(
            "Analiza de sensibilitate SAR a fost calculată separat de rezultatul final."
        )
        return True
    except Exception as exc:
        state.analysis_results["sar_qa_error"] = str(exc)
        return False
    finally:
        record_timing(state, "QA SAR", perf_counter() - started)
        state.sar_qa_requested = False


def execute_osm_loading(
    state: ImpactToolState,
    progress_callback: ProgressCallback | None = None,
    gee_status: Any | None = None,
) -> bool:
    invalidate_report(state)
    if not state.analysis_complete:
        state.analysis_error = "Datele OSM pot fi încărcate numai după analiza SAR."
        return False
    try:
        osm_started = perf_counter()
        water_geometry = (
            state.analysis_results.get("sar", {}).get("new_water_geometry")
        )
        if not water_geometry:
            raise RuntimeError("Geometria vectorială a apei noi SAR nu este disponibilă.")
        result = fetch_targeted_impact(
            water_geometry=water_geometry,
            buffer_meters=state.buffer_meters,
        )
        raw_elements = [
            element
            for elements in result.data.get("categories", {}).values()
            for element in elements
        ]
        layers = build_osm_geojson_layers(raw_elements)
        important = state.analysis_results.get("important_features")
        if important:
            layers["osm_critical"] = important
        state.analysis_results["osm_raw"] = {
            "layers": layers,
            "metadata": result.data.get("metadata", {}),
            "attribution": "© OpenStreetMap contributors",
        }
        category_results = result.data.get("categories", {})
        state.osm_status = {
            category: {
                "ok": result.data.get("metadata", {})
                .get("category_status", {})
                .get(category, {})
                .get("ok", result.status.ok),
                "source": result.status.source,
                "completeness": result.status.completeness,
                "duration_seconds": result.status.duration_seconds,
                "warnings": [result.status.warning] if result.status.warning else [],
                "raw_elements": len(elements),
                "last_run": datetime.now(UTC).isoformat(),
            }
            for category, elements in category_results.items()
        }
        category_layers = {
            "buildings": "osm_buildings",
            "roads": "osm_roads",
            "railways": "osm_railways",
            "bridges": "osm_bridges",
        }
        for category, layer_id in category_layers.items():
            if category in state.osm_status:
                state.osm_status[category]["parsed_features"] = len(
                    layers.get(layer_id, {}).get("features", [])
                )
        state.external_api_status["overpass"] = {
            "ok": result.status.ok,
            "source": result.status.source,
            "completeness": result.status.completeness,
            "warning": result.status.warning,
            "duration_seconds": result.status.duration_seconds,
            "last_run": datetime.now(UTC).isoformat(),
        }
        record_timing(state, "încărcare OSM țintită", perf_counter() - osm_started)
        _progress(
            state,
            progress_callback,
            92,
            "Clasificare impact OSM direct și în buffer",
        )
        impact_ready = recalculate_osm_impact(state)
        if impact_ready:
            for category, layer_id in category_layers.items():
                if category in state.osm_status:
                    state.osm_status[category]["display_features"] = len(
                        state.analysis_results["osm_impact"]
                        .get("layers", {})
                        .get(layer_id, {})
                        .get("display_features", [])
                    )
        if not impact_ready:
            state.analysis_results["osm_load_status"] = "impact_osm_indisponibil"
        state.osm_impact_available = impact_ready
        state.analysis_results.setdefault("sar_status", {})[
            "osm_impact_available"
        ] = impact_ready
        return impact_ready
    except Exception as exc:
        state.analysis_results["osm_load_status"] = "osm_indisponibil"
        state.external_api_status["overpass"] = {
            "ok": False,
            "warning": str(exc),
            "completeness": "indisponibil",
        }
        state.osm_impact_available = False
        return False
    finally:
        state.osm_load_requested = False
        state.osm_impact_requested = False
        state.osm_retry_category = ""


def _osm_load_status(statuses: dict[str, dict[str, Any]]) -> str:
    if not statuses:
        return "osm_indisponibil"
    if all(
        status.get("ok") is True
        and status.get("completeness") == "complet"
        for status in statuses.values()
    ):
        return "osm_complet"
    if any(status.get("ok") for status in statuses.values()):
        return "osm_parțial"
    return "osm_indisponibil"


def _osm_partial_reasons(
    statuses: dict[str, dict[str, Any]],
) -> list[str]:
    reasons = []
    for category, status in statuses.items():
        if not status.get("ok"):
            reason = status.get("error") or "categoria nu a putut fi încărcată"
            reasons.append(f"{category}: {reason}")
        elif status.get("completeness") != "complet":
            completeness = status.get("completeness") or "necunoscută"
            reasons.append(f"{category}: completitudine {completeness}")
    return reasons


def recalculate_osm_impact(state: ImpactToolState) -> bool:
    invalidate_report(state)
    raw = state.analysis_results.get("osm_raw")
    sar = state.analysis_results.get("sar")
    water_geometry = (sar or {}).get("new_water_geometry")
    if not raw or not water_geometry:
        return False
    layers = raw.get("layers") or {}
    if not layers:
        return False
    impact_started = perf_counter()
    impact = classify_osm_impact(
        layers,
        water_geometry,
        state.buffer_meters,
        active_geometry=state.active_geometry,
        projection_cache_key=_projection_cache_key(water_geometry, raw),
    )
    compact_layers = {}
    for layer_id, collection in impact.get("layers", {}).items():
        display_features = collection.get(
            "display_features",
            collection.get("features", []),
        )
        compact_layers[layer_id] = {
            key: value
            for key, value in collection.items()
            if key not in {"features", "analysis_features", "display_features"}
        }
        compact_layers[layer_id]["features"] = display_features
        compact_layers[layer_id]["display_features"] = display_features
    state.analysis_results["osm_impact"] = {
        **impact,
        "layers": compact_layers,
    }
    metrics = state.analysis_results["osm_impact"].setdefault("metrics", {})
    metrics["important_features_direct"] = metrics.get("critical_direct", 0)
    metrics["important_features_buffer"] = metrics.get("critical_buffer", 0)
    state.osm_impact_available = True
    state.map_data_revision += 1
    record_timing(state, "impact OSM", perf_counter() - impact_started)
    state.cache_events.append(
        f"Impactul OSM a fost recalculat pentru bufferul de {state.buffer_meters} m."
    )
    return True


def _projection_cache_key(
    water_geometry: dict[str, Any],
    raw_osm: dict[str, Any],
) -> str:
    payload = {
        "water": water_geometry,
        "revision": raw_osm.get("metadata", {}),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def execute_important_features(state: ImpactToolState) -> bool:
    invalidate_report(state)
    if not state.analysis_complete:
        return False
    west, south, east, north = state.active_area_bbox
    result = fetch_important_facilities(
        filter_value=f"rect:{west},{south},{east},{north}",
        fallback=lambda: _overpass_important_fallback(
            [west, south, east, north],
            state.analysis_mode,
        ),
    )
    state.external_api_status["important_features"] = {
        "ok": result.status.ok,
        "source": result.status.source,
        "warning": result.status.warning,
        "completeness": result.status.completeness,
        "duration_seconds": result.status.duration_seconds,
    }
    if result.status.ok:
        state.analysis_results["important_features"] = result.data
        raw_osm = state.analysis_results.get("osm_raw")
        if raw_osm:
            raw_osm.setdefault("layers", {})["osm_critical"] = result.data
            metadata = raw_osm.setdefault("metadata", {})
            metadata["important_features_revision"] = (
                int(metadata.get("important_features_revision", 0)) + 1
            )
            previous_revision = state.map_data_revision
            recalculate_osm_impact(state)
            if state.map_data_revision == previous_revision:
                state.map_data_revision += 1
    state.important_features_requested = False
    record_timing(state, "obiective importante", result.status.duration_seconds)
    return result.status.ok


def _overpass_important_fallback(
    bbox: list[float],
    analysis_mode: str,
) -> ExternalResult:
    query = build_category_query(
        bbox,
        "critical",
        analysis_mode=analysis_mode,
    )
    raw = run_targeted_query(query)
    if not raw.status.ok:
        return raw
    layers = build_osm_geojson_layers((raw.data or {}).get("elements", []))
    return ExternalResult.success(
        layers.get(
            "osm_critical",
            {"type": "FeatureCollection", "features": []},
        ),
        source=raw.status.source,
        duration_seconds=raw.status.duration_seconds,
        completeness=raw.status.completeness,
        warning=raw.status.warning,
    )


def _progress(
    state: ImpactToolState,
    callback: ProgressCallback | None,
    percent: int,
    stage: str,
) -> None:
    state.analysis_progress = max(0, min(100, int(percent)))
    state.analysis_stage = stage
    if callback:
        callback(state.analysis_progress, stage)

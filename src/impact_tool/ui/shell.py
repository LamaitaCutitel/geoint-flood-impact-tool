from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Any

from src.gee.gee_auth import local_earthengine_status
from src.app_support.county_boundaries import (
    county_display_name,
    county_geometry,
    feature_bbox,
)
from src.impact_tool.aoi import geometry_from_drawing
from src.impact_tool.analysis import (
    execute_analysis,
    execute_dynamic_world,
    execute_important_features,
    execute_sar_qa,
    execute_osm_loading,
    recalculate_osm_impact,
)
from src.impact_tool.dynamic_world import dynamic_world_layer_definitions
from src.impact_tool.external.maptiler import county_buildings_context
from src.impact_tool.map.builder import build_shell_map
from src.impact_tool.models import APP_SUBTITLE, APP_TITLE, LAYER_GROUPS
from src.impact_tool.osm_impact import visible_impact_layers
from src.impact_tool.report import (
    generate_cached_report,
    report_filename,
    save_report_pdf,
    validate_report_pdf,
)
from src.impact_tool.sar import sar_layer_definitions
from src.impact_tool.sar_qa import sar_qa_layer_definitions
from src.impact_tool.state import initialize_state, record_timing, set_aoi
from src.impact_tool.ui.results import render_result_tabs
from src.impact_tool.ui.sidebar import render_scene_explorer, render_sidebar


def render_app(st_module: Any | None = None) -> None:
    if st_module is None:
        import streamlit as st_module

    st = st_module
    st.set_page_config(
        page_title=APP_TITLE,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles(st)
    state = initialize_state(st.session_state)
    gee_status = local_earthengine_status()

    header_left, header_status, header_action = st.columns([4.6, 2.4, 1.8])
    with header_left:
        st.title(APP_TITLE)
        st.caption(APP_SUBTITLE)
    with header_status:
        status = "GEE conectat" if gee_status.available else "GEE neconectat"
        aoi_status = "AOI activ" if state.aoi_active else "AOI inactiv"
        st.markdown(
            f'<div class="status-row"><span>{status}</span>'
            f'<span>Județ: {state.county_name}</span><span>{aoi_status}</span></div>',
            unsafe_allow_html=True,
        )
    with header_action:
        if state.report_bytes:
            st.download_button(
                "Generează și descarcă raportul PDF",
                data=state.report_bytes,
                file_name=state.report_filename,
                mime="application/pdf",
                type="primary",
                use_container_width=True,
                key="download_impact_pdf",
            )
        elif st.button(
            "Generează și descarcă raportul PDF",
            type="primary",
            use_container_width=True,
            disabled=not state.can_download_report,
            help="Raportul devine disponibil după finalizarea analizei.",
            key="generate_impact_pdf",
        ):
            state.report_requested = True

    counties_geojson, boundary_warnings = render_sidebar(st, state)
    render_scene_explorer(st, state)
    if state.run_requested:
        progress_bar = st.progress(0, text="Pornire analiză")
        status_box = st.empty()

        def update_progress(percent: int, stage: str) -> None:
            progress_bar.progress(percent, text=stage)
            status_box.info(stage)

        success = execute_analysis(
            state,
            progress_callback=update_progress,
            load_osm=False,
            mode=state.analysis_mode,
        )
        if success:
            status_box.success(
                "Analiza SAR a fost finalizată. Etapele externe pot fi rulate separat."
            )
        else:
            status_box.error(state.analysis_error or "Analiza nu a putut fi finalizată.")

    if state.osm_load_requested:
        with st.spinner("Se încarcă și se analizează obiectele OSM țintite..."):
            execute_osm_loading(state)
        st.rerun()

    if state.important_features_requested:
        with st.spinner("Se încarcă obiectivele importante..."):
            execute_important_features(state)
        st.rerun()

    if state.dynamic_world_requested:
        with st.spinner("Se rulează Dynamic World și corelarea multisursă..."):
            execute_dynamic_world(state)
        st.rerun()

    if state.sar_qa_requested:
        with st.spinner("Se rulează analiza de sensibilitate SAR..."):
            execute_sar_qa(state)
        st.rerun()

    if state.report_requested:
        with st.spinner("Se generează raportul PDF..."):
            report_started = perf_counter()
            state.report_bytes, from_cache = generate_cached_report(state)
            record_timing(state, "PDF", perf_counter() - report_started)
            state.report_filename = report_filename(state)
            saved_path = save_report_pdf(state, state.report_bytes)
            state.analysis_results["pdf_validation"] = validate_report_pdf(
                state.report_bytes,
                saved_path,
            )
            state.report_requested = False
            state.cache_events.append(
                "Raport PDF încărcat din cache."
                if from_cache
                else "Raport PDF generat și salvat în cache."
            )
            state.cache_events.append(f"Raport PDF salvat local: {saved_path}")
        st.rerun()

    if state.analysis_results.get("osm_raw") and not state.analysis_results.get("osm_impact"):
        recalculate_osm_impact(state)
    if state.analysis_error:
        st.error(state.analysis_error)
    if state.analysis_progress:
        st.progress(state.analysis_progress, text=state.analysis_stage)
    for warning in boundary_warnings or []:
        st.warning(warning)

    building_context = county_buildings_context()
    map_column, layers_column = st.columns([4.7, 1.3], gap="small")
    with layers_column:
        st.markdown('<div class="layers-title">Layere</div>', unsafe_allow_html=True)
        if not building_context.status.ok:
            st.caption(building_context.status.warning)
        _render_layer_controls(st, state)

    with map_column:
        from streamlit_folium import st_folium

        focus_location = list(state.map_focus)
        map_started = perf_counter()
        impact_map = build_shell_map(
            counties_geojson,
            state.county_name,
            aoi_geometry=state.aoi_geometry,
            preview_tiles=(
                state.scene_compare_tiles
                if state.scene_compare_active and not state.layer_compare_active
                else {}
            ),
            layer_compare_layers=(
                _comparison_layers(state) if state.analysis_complete else {}
            ),
            layer_compare_left_id=state.layer_compare_left_id,
            layer_compare_right_id=state.layer_compare_right_id,
            layer_compare_active=(
                state.layer_compare_active and not state.scene_compare_active
            ),
            preview_scene_tile=(
                state.preview_scene_tile if not state.analysis_complete else ""
            ),
            analysis_layers=_analysis_layers(state),
            buffer_geometry=_selected_buffer_geometry(state),
            osm_layers=_visible_osm_layers(state),
            building_context_tile=(
                building_context.data["tile_url"]
                if building_context.status.ok
                else None
            ),
            focus_location=focus_location,
        )
        record_timing(state, "hartă", perf_counter() - map_started)
        map_data = st_folium(
            impact_map,
            use_container_width=True,
            height=640,
            returned_objects=[
                "last_active_drawing",
                "all_drawings",
                "last_object_clicked_tooltip",
            ],
            key=_map_render_key(state, focus_location),
        )
        if focus_location:
            state.map_focus = []
        drawing = geometry_from_drawing((map_data or {}).get("last_active_drawing"))
        if drawing and set_aoi(state, drawing):
            st.rerun()
        clicked_county = _county_feature_from_click(
            counties_geojson,
            (map_data or {}).get("last_object_clicked_tooltip"),
        )
        if clicked_county and set_county(
            state,
            county_display_name(clicked_county),
            county_geometry(clicked_county),
            feature_bbox(clicked_county),
        ):
            st.rerun()

    render_result_tabs(st, state)


def _map_render_key(state: Any, focus_location: list[float] | None = None) -> str:
    payload = {
        "county": state.county_name,
        "area": state.active_area_hash or "county",
        "analysis": state.analysis_hash or "empty",
        "layers": sorted(state.active_layers),
        "buffer": state.buffer_meters,
        "preview_scene": state.preview_scene_id,
        "preview_tile": state.preview_scene_tile,
        "preview_mode": state.preview_mode,
        "scene_compare": state.scene_compare_active,
        "scene_compare_tiles": state.scene_compare_tiles,
        "layer_compare": state.layer_compare_active,
        "layer_compare_left": state.layer_compare_left_id,
        "layer_compare_right": state.layer_compare_right_id,
        "osm_filters": state.osm_filters,
        "critical_mode": state.critical_mode,
        "presentation_mode": state.presentation_mode,
        "focus": focus_location or [],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:20]
    return f"impact-map-{digest}"


def _analysis_layers(state: Any) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    if state.analysis_results.get("sar"):
        layers.extend(sar_layer_definitions(state.analysis_results["sar"]))
    if state.analysis_results.get("sar_qa"):
        layers.extend(sar_qa_layer_definitions(state.analysis_results["sar_qa"]))
    if state.analysis_results.get("dynamic_world"):
        layers.extend(
            dynamic_world_layer_definitions(state.analysis_results["dynamic_world"])
        )
    return [
        layer
        for layer in layers
        if layer["id"] in state.active_layers
    ]


def _comparison_layers(state: Any) -> dict[str, dict[str, str]]:
    definitions: list[dict[str, Any]] = []
    if state.analysis_results.get("sar"):
        definitions.extend(sar_layer_definitions(state.analysis_results["sar"]))
    if state.analysis_results.get("sar_qa"):
        definitions.extend(
            sar_qa_layer_definitions(state.analysis_results["sar_qa"])
        )
    if state.analysis_results.get("dynamic_world"):
        definitions.extend(
            dynamic_world_layer_definitions(state.analysis_results["dynamic_world"])
        )
    layers = {
        item["id"]: {
            "name": item["name"],
            "url": item.get("tile_url") or "",
            "attribution": "Google Earth Engine",
        }
        for item in definitions
    }
    layers["basemap_satellite"] = {
        "name": "Basemap satelit",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "attribution": "Esri, Maxar, Earthstar Geographics",
    }
    layers["basemap_osm_light"] = {
        "name": "Basemap OSM Light",
        "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attribution": "OpenStreetMap contributors, CARTO",
    }
    return layers


def _visible_osm_layers(state: Any) -> dict[str, dict[str, Any]]:
    impact = state.analysis_results.get("osm_impact")
    if not impact:
        return {}
    visible = visible_impact_layers(
        impact,
        state.osm_filters,
        state.critical_mode,
    )
    selected = {
        layer_id: layer
        for layer_id, layer in visible.items()
        if layer_id in state.active_layers
    }
    if not state.presentation_mode:
        return selected
    return {
        layer_id: {
            **layer,
            "features": [
                feature
                for feature in layer.get("features", [])
                if feature.get("properties", {}).get("infrastructure_level")
                in {"esențial", "important"}
            ],
        }
        for layer_id, layer in selected.items()
    }


def _grouped_layer_definitions(state: Any) -> dict[str, list[dict[str, Any]]]:
    groups = {group: [] for group in LAYER_GROUPS}
    sar = state.analysis_results.get("sar")
    if sar:
        groups["Analiză SAR"] = sar_layer_definitions(sar)
        if state.analysis_results.get("sar_qa"):
            groups["Analiză SAR"].extend(
                sar_qa_layer_definitions(state.analysis_results["sar_qa"])
            )
    dynamic = state.analysis_results.get("dynamic_world")
    if dynamic:
        definitions = dynamic_world_layer_definitions(dynamic)
        groups["Dynamic World"] = definitions[:4]
        groups["Corelare multisursă"] = definitions[4:]
    impact = state.analysis_results.get("osm_impact")
    if impact:
        names = {
            "osm_buildings": "Clădiri potențial expuse",
            "osm_roads": "Drumuri potențial expuse",
            "osm_railways": "Căi ferate intersectate",
            "osm_bridges": "Poduri intersectate",
            "osm_critical": "Obiective critice potențial expuse",
        }
        groups["Impact OSM"] = [
            {"id": layer_id, "name": names.get(layer_id, layer_id)}
            for layer_id in impact.get("layers", {})
        ]
    return groups


def _render_layer_controls(st: Any, state: Any) -> None:
    groups = _grouped_layer_definitions(state)
    any_layers = False
    for group in LAYER_GROUPS:
        with st.expander(group, expanded=True):
            definitions = groups.get(group, [])
            if group == "Impact OSM" and state.analysis_results.get("osm_impact"):
                definitions = [
                    {"id": "buffer", "name": "Buffer de avertizare"},
                    *definitions,
                ]
            if not definitions:
                st.caption("Niciun strat disponibil în etapa curentă.")
                continue
            any_layers = True
            for layer in definitions:
                layer_id = layer["id"]
                selected = st.checkbox(
                    layer["name"],
                    value=layer_id in state.active_layers,
                    key=f"impact-layer-{state.analysis_hash or 'empty'}-{layer_id}",
                )
                if selected and layer_id not in state.active_layers:
                    state.active_layers.append(layer_id)
                elif not selected and layer_id in state.active_layers:
                    state.active_layers.remove(layer_id)
    if state.analysis_results.get("osm_impact"):
        _render_osm_map_filters(st, state)
    if any_layers:
        st.caption("Harta încarcă numai layerele bifate.")


def _render_osm_map_filters(st: Any, state: Any) -> None:
    st.markdown("##### Filtre OSM")
    labels = {
        "buildings": "Clădiri",
        "roads": "Drumuri",
        "railways": "Căi ferate",
        "bridges": "Poduri",
        "critical": "Obiective critice",
        "reference_buildings": "Clădiri de referință",
    }
    for key, label in labels.items():
        state.osm_filters[key] = st.checkbox(
            label,
            value=state.osm_filters.get(key, True),
            key=f"osm_map_filter_{key}",
        )
    state.critical_mode = st.toggle(
        "Doar impact critic",
        value=state.critical_mode,
        key="osm_map_critical_mode",
        help="Păstrează apa nouă SAR, bufferul, drumurile, podurile și obiectivele critice.",
    )


def _selected_buffer_geometry(state: Any) -> dict[str, Any] | None:
    if "buffer" not in state.active_layers:
        return None
    return (state.analysis_results.get("osm_impact") or {}).get("buffer_geometry")


def _county_feature_from_click(
    counties_geojson: dict[str, Any] | None,
    tooltip: Any,
) -> dict[str, Any] | None:
    clicked_name = str(tooltip or "").strip()
    if not counties_geojson or not clicked_name:
        return None
    for feature in counties_geojson.get("features", []):
        properties = feature.get("properties", {})
        names = {
            str(properties.get(key) or "").strip()
            for key in ("NAME_LATN", "NUTS_NAME", "NAME")
        }
        if clicked_name in names or clicked_name == county_display_name(feature):
            return feature
    return None


def _inject_styles(st: Any) -> None:
    st.markdown(
        """
        <style>
          .stApp { background:#090d14; color:#e5e7eb; }
          [data-testid="stHeader"] { background:rgba(9,13,20,.96); }
          [data-testid="stSidebar"] {
            background:#111827; border-right:1px solid #334155;
          }
          [data-testid="stSidebar"] > div:first-child { padding-top:1.1rem; }
          .block-container { max-width:1800px; padding-top:1.15rem; padding-bottom:1rem; }
          h1, h2, h3, h4, p, label { color:#e5e7eb; }
          h1 { font-size:2rem !important; letter-spacing:0 !important; }
          .status-row {
            display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; padding-top:13px;
          }
          .status-row span {
            border:1px solid #166534; background:#052e16; color:#bbf7d0;
            border-radius:999px; padding:7px 11px; font-size:.82rem; white-space:nowrap;
          }
          .scene-timeline {
            background:#111827; border:1px solid #334155; color:#e5e7eb;
            display:flex; flex-direction:column; gap:8px; margin:4px 0 14px;
            max-height:110px; overflow:auto; padding:12px;
          }
          .scene-timeline span { color:#cbd5e1; line-height:1.6; }
          .impact-sidebar-title, .layers-title {
            color:#f8fafc; font-size:1rem; font-weight:700; margin-bottom:10px;
          }
          .workflow-step {
            display:flex; align-items:center; gap:9px; margin:7px 0; color:#94a3b8;
          }
          .workflow-step span {
            align-items:center; background:#334155; border-radius:50%; color:#e2e8f0;
            display:flex; font-size:.75rem; font-weight:700; height:24px;
            justify-content:center; width:24px;
          }
          .workflow-step p { margin:0; font-size:.88rem; }
          .workflow-step.done span, .workflow-step.active span { background:#2563eb; color:white; }
          .workflow-step.active p { color:#f8fafc; font-weight:700; }
          .active-area {
            border:1px solid #166534; background:#052e16; border-radius:6px;
            display:flex; flex-direction:column; margin:10px 0; padding:10px 12px;
          }
          .active-area span { color:#bbf7d0; font-size:.82rem; }
          .swipe-placeholder {
            align-items:center; background:#030712; border:1px solid #334155;
            border-radius:6px; color:white; display:flex; height:90px;
            justify-content:center; margin-top:14px; font-weight:700;
          }
          [data-testid="stIFrame"] {
            border:1px solid #334155; border-radius:6px; overflow:hidden;
          }
          [data-testid="stExpander"], [data-testid="stMetric"] {
            background:#111827; border-color:#334155;
          }
          [data-baseweb="select"] > div, [data-baseweb="input"] > div {
            background:#0f172a; border-color:#475569; color:#f8fafc;
          }
          button { border-radius:6px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

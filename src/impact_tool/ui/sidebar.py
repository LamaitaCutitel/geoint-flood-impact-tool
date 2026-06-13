from __future__ import annotations

from datetime import date, timedelta
from time import perf_counter
from typing import Any

from src.app_support.county_boundaries import (
    county_geometry,
    county_names,
    feature_bbox,
    load_or_download_counties,
    selected_county_feature,
)
from src.gee.gee_auth import initialize_earth_engine
from src.gee.sentinel1_collection import build_aoi_from_geometry
from src.gee.sentinel1_scene_explorer import search_sentinel1_scenes_result
from src.impact_tool.cache import PersistentCache
from src.impact_tool.analysis import recalculate_osm_impact
from src.impact_tool.models import BUFFER_MAX_METERS, BUFFER_MIN_METERS, ImpactToolState
from src.impact_tool.presets import GALATI_PRESET_NAME, apply_galati_preset
from src.impact_tool.sar import recommended_sar_threshold
from src.impact_tool.scenes import (
    confirm_scene_pair,
    hydrate_scene_thumbnails,
    preview_tile_for_scene,
    preview_tiles_for_pair,
    scene_label,
    search_scenes,
    select_scene_pair,
    timeline_entries,
)
from src.impact_tool.state import (
    apply_scene_pair,
    clear_aoi,
    record_timing,
    reset_comparison,
    set_county,
    update_buffer,
    update_sar_parameters,
)
from src.impact_tool.workflow import workflow_steps


def render_sidebar(st: Any, state: ImpactToolState) -> tuple[dict | None, list[str]]:
    boundary_result = load_or_download_counties()
    counties = county_names(boundary_result.geojson) if boundary_result.geojson else []

    with st.sidebar:
        st.markdown('<div class="impact-sidebar-title">Pașii analizei</div>', unsafe_allow_html=True)
        for step in workflow_steps(state):
            status_class = "done" if step.complete else ("active" if step.active else "waiting")
            st.markdown(
                f'<div class="workflow-step {status_class}">'
                f'<span>{step.number}</span><p>{step.label}</p></div>',
                unsafe_allow_html=True,
            )

        st.divider()
        galati_feature = (
            selected_county_feature(boundary_result.geojson, "Galati")
            if boundary_result.geojson
            else None
        )
        if st.button(
            GALATI_PRESET_NAME,
            use_container_width=True,
            key="apply_galati_preset",
        ):
            apply_galati_preset(
                state,
                st.session_state,
                county_geometry(galati_feature),
                feature_bbox(galati_feature),
            )
            st.rerun()
        selected_index = counties.index(state.county_name) if state.county_name in counties else 0
        selected_county = st.selectbox(
            "Județ",
            counties or [state.county_name],
            index=selected_index,
            help="Selectează județul folosit ca arie implicită a analizei.",
        )
        selected_feature = (
            selected_county_feature(boundary_result.geojson, selected_county)
            if boundary_result.geojson
            else None
        )
        if set_county(
            state,
            selected_county,
            county_geometry(selected_feature),
            feature_bbox(selected_feature),
        ):
            st.rerun()

        area_label = "Zonă focală desenată manual" if state.aoi_active else "Județ complet"
        st.markdown(
            f'<div class="active-area"><strong>Aria activă</strong><span>{area_label}</span></div>',
            unsafe_allow_html=True,
        )
        st.radio(
            "Aria activă",
            ["Județ complet", "Zonă focală desenată manual"],
            index=1 if state.aoi_active else 0,
            disabled=True,
            help="Zona focală devine activă după desenarea și validarea unui poligon pe hartă.",
            label_visibility="collapsed",
        )
        if st.button(
            "Desenează zonă focală",
            use_container_width=True,
            help="Folosește apoi instrumentul poligon sau dreptunghi din colțul stâng al hărții.",
        ):
            state.draw_requested = True
        if state.draw_requested and not state.aoi_active:
            st.info("Desenează un singur poligon pe hartă. Acesta va fi validat automat.")
        if state.aoi_active:
            st.caption(
                f"Suprafață: {state.active_area_km2:.2f} km² · "
                f"Hash: {state.active_area_hash}"
            )
            if st.button(
                "Șterge AOI și revino la județ",
                use_container_width=True,
                type="secondary",
            ):
                clear_aoi(state)
                st.rerun()
        for warning in state.area_warnings:
            st.warning(warning)
        for error in state.area_errors:
            st.error(error)

        _render_scene_selection(st, state)

        if state.analysis_results.get("osm_raw"):
            with st.form("osm_buffer_form"):
                selected_buffer = st.slider(
                    "Buffer avertizare",
                    min_value=BUFFER_MIN_METERS,
                    max_value=BUFFER_MAX_METERS,
                    value=state.buffer_meters,
                    step=1,
                    help="Distanța de avertizare pentru elementele potențial expuse.",
                )
                apply_buffer = st.form_submit_button(
                    "Aplică și recalculează impactul OSM",
                    use_container_width=True,
                )
            if apply_buffer and update_buffer(state, selected_buffer):
                recalculate_osm_impact(state)
                st.rerun()
        else:
            selected_buffer = st.slider(
                "Buffer în jurul apei noi",
                min_value=BUFFER_MIN_METERS,
                max_value=BUFFER_MAX_METERS,
                value=state.buffer_meters,
                step=1,
                help="Distanța de avertizare pentru evaluarea elementelor potențial expuse.",
            )
            update_buffer(state, selected_buffer)

        run_complete = st.button(
            "Rulează analiza completă",
            type="primary",
            use_container_width=True,
            disabled=not state.can_run_analysis,
            help=(
                "Rulează SAR strict BEFORE / AFTER, Dynamic World și impactul OSM. "
                "Etapele opționale nu șterg rezultatul SAR dacă devin indisponibile."
            ),
            key="run_complete_analysis",
        )
        if run_complete:
            state.analysis_mode = "rapid"
            state.run_requested = True

        with st.expander("Opțiuni avansate", expanded=False):
            state.scene_search_polarization = st.selectbox(
                "Polarizare",
                ["VH", "VV"],
                index=["VH", "VV"].index(state.scene_search_polarization),
                help="Polarizarea folosită la următoarea căutare Sentinel-1.",
            )
            state.scene_search_orbit_pass = st.selectbox(
                "Orbit pass",
                ["BOTH", "ASCENDING", "DESCENDING"],
                index=["BOTH", "ASCENDING", "DESCENDING"].index(
                    state.scene_search_orbit_pass
                ),
                help="Direcția orbitei folosită la următoarea căutare.",
            )
            polarization_for_threshold = (
                (state.before_scene or {}).get("polarization")
                or state.scene_query.get("polarization")
                or "VH"
            )
            threshold_modes = ["conservator", "echilibrat", "sensibil", "manual"]
            threshold_mode = st.selectbox(
                "Mod prag SAR",
                threshold_modes,
                index=threshold_modes.index(state.sar_threshold_mode),
            )
            if threshold_mode == "manual":
                water_threshold = st.number_input(
                    "Prag apă SAR manual (dB)",
                    min_value=-30.0,
                    max_value=-5.0,
                    value=float(state.analysis_parameters["water_threshold"]),
                    step=0.5,
                    help="Valoarea manuală este păstrată când polarizarea se schimbă.",
                )
            else:
                water_threshold = recommended_sar_threshold(
                    polarization_for_threshold,
                    threshold_mode,
                )
                st.caption(
                    f"Recomandare {polarization_for_threshold} / {threshold_mode}: "
                    f"{water_threshold:.1f} dB"
                )
            state.sar_threshold_mode = threshold_mode
            smoothing_meters = st.slider(
                "Smoothing SAR (m)",
                0,
                100,
                int(state.analysis_parameters["smoothing_meters"]),
                step=10,
            )
            minimum_connected_pixels = st.slider(
                "Minimum connected pixels",
                0,
                50,
                int(state.analysis_parameters["minimum_connected_pixels"]),
                step=1,
            )
            analysis_scale_meters = st.select_slider(
                "Scara metricilor SAR (m)",
                options=[10, 20, 30],
                value=int(state.analysis_parameters.get("analysis_scale_meters", 10)),
            )
            vectorization_scale_meters = st.select_slider(
                "Scara vectorizării SAR (m)",
                options=[10, 20, 30],
                value=int(
                    state.analysis_parameters.get(
                        "vectorization_scale_meters",
                        analysis_scale_meters,
                    )
                ),
            )
            minimum_polygon_area_m2 = st.number_input(
                "Suprafață minimă poligon operațional (m²)",
                min_value=0,
                max_value=100000,
                value=int(
                    state.analysis_parameters.get(
                        "minimum_polygon_area_m2",
                        1000,
                    )
                ),
                step=100,
            )
            simplification_tolerance_m = st.slider(
                "Toleranță simplificare hartă (m)",
                0,
                100,
                int(
                    state.analysis_parameters.get(
                        "geometry_simplification_tolerance_m",
                        10,
                    )
                ),
                step=5,
            )
            update_sar_parameters(
                state,
                water_threshold=float(water_threshold),
                smoothing_meters=int(smoothing_meters),
                minimum_connected_pixels=int(minimum_connected_pixels),
                analysis_scale_meters=int(analysis_scale_meters),
                vectorization_scale_meters=int(vectorization_scale_meters),
                minimum_polygon_area_m2=int(minimum_polygon_area_m2),
                geometry_simplification_tolerance_m=int(
                    simplification_tolerance_m
                ),
            )
            if analysis_scale_meters != vectorization_scale_meters:
                st.warning(
                    "Scara vectorizării diferă de scara metricilor. Rasterul SAR "
                    "rămâne autoritativ pentru suprafață."
                )
            if state.sar_parameters_message:
                st.warning(state.sar_parameters_message)

        if state.comparison_ready:
            scene_compare_active = st.toggle(
                "Activează bara BEFORE / AFTER",
                value=state.scene_compare_active,
                help="Încarcă imaginile selectate și afișează separatorul vertical pe hartă.",
            )
            if scene_compare_active != state.scene_compare_active:
                state.scene_compare_active = scene_compare_active
                state.swipe_enabled = scene_compare_active
                state.layer_compare_active = False
                if scene_compare_active and not state.scene_compare_tiles:
                    _refresh_preview_tiles(state)
                st.rerun()
            selected_preview_mode = st.radio(
                "Mod comparație",
                ["Radar brut în tonuri de gri", "Doar apă observată prin SAR"],
                index=0 if state.preview_mode == "Radar brut în tonuri de gri" else 1,
                disabled=not state.scene_compare_active,
                help="Schimbă reprezentarea comparatorului fără a porni analiza finală.",
            )
            if selected_preview_mode != state.preview_mode:
                state.preview_mode = selected_preview_mode
                _refresh_preview_tiles(state)
                st.rerun()
            if state.scene_compare_active:
                st.caption("Comparatorul vertical este activ pe hartă.")
        else:
            st.markdown(
                '<div class="swipe-placeholder">Comparație BEFORE / AFTER</div>',
                unsafe_allow_html=True,
            )
            st.caption("Comparatorul glisant va fi disponibil după selectarea celor două scene.")

    return boundary_result.geojson, boundary_result.warnings


def _render_scene_selection(st: Any, state: ImpactToolState) -> None:
    st.markdown("#### Scene Sentinel-1")
    today = date.today()
    preset_suffix = "_preset" if state.preset_name == GALATI_PRESET_NAME else ""
    start_key = f"impact_scene_start{preset_suffix}"
    start_value = st.session_state.pop(
        start_key,
        today - timedelta(days=60),
    )
    start_date = st.date_input(
        "Început interval",
        value=start_value,
        key=start_key,
    )
    end_key = f"impact_scene_end{preset_suffix}"
    end_value = st.session_state.pop(end_key, today)
    end_date = st.date_input(
        "Sfârșit interval",
        value=end_value,
        key=end_key,
    )
    polarization = state.scene_search_polarization
    orbit_pass = state.scene_search_orbit_pass
    if st.button("Caută scene Sentinel-1", use_container_width=True):
        gee = initialize_earth_engine()
        if not gee.available or gee.ee is None:
            state.scene_errors = [gee.message]
        else:
            aoi = build_aoi_from_geometry(gee.ee, state.active_geometry, state.active_area_bbox)
            scenes_started = perf_counter()
            result = search_scenes(
                cache=PersistentCache(),
                aoi_hash=state.active_area_hash,
                start_date=str(start_date),
                end_date=str(end_date),
                polarization=polarization,
                orbit_pass=orbit_pass,
                searcher=search_sentinel1_scenes_result,
                search_args=(gee.ee, aoi),
            )
            record_timing(state, "scene", perf_counter() - scenes_started)
            thumbnails_started = perf_counter()
            state.scene_candidates, thumbnail_hits = hydrate_scene_thumbnails(
                cache=PersistentCache(),
                ee=gee.ee,
                aoi=aoi,
                aoi_hash=state.active_area_hash,
                scenes=result.scenes,
                max_thumbnails=state.scene_gallery_limit,
            )
            record_timing(
                state,
                "thumbnail-uri",
                perf_counter() - thumbnails_started,
            )
            state.scene_warnings = result.warnings
            state.scene_errors = result.errors
            state.scene_current_id = (
                str(state.scene_candidates[0].get("ee_id"))
                if state.scene_candidates
                else ""
            )
            state.scene_query = {
                "start_date": str(start_date),
                "end_date": str(end_date),
                "polarization": polarization,
                "orbit_pass": orbit_pass,
            }
            state.cache_events.append(
                "Scene Sentinel-1 disponibile în cache."
                if result.from_cache
                else "Scene Sentinel-1 încărcate din Google Earth Engine."
            )
            state.cache_events.append(
                f"Thumbnail-uri Sentinel-1 din cache: {thumbnail_hits}/"
                f"{len(state.scene_candidates)}."
            )

    for error in state.scene_errors:
        st.error(error)
    for warning in state.scene_warnings:
        st.warning(warning)
    st.caption(
        f"{len(state.scene_candidates)} scene disponibile. "
        "Exploratorul și selecția perechii sunt afișate în zona principală."
    )


def render_scene_explorer(st: Any, state: ImpactToolState) -> None:
    st.markdown("### Explorator temporal Sentinel-1")
    if not state.scene_candidates:
        st.info(
            "Configurează parametrii în sidebar și apasă „Caută scene Sentinel-1”."
        )
        return

    _render_scene_timeline(st, state.scene_candidates)
    _render_current_scene(st, state)
    _render_scene_gallery(st, state)
    _render_scene_pair(st, state)


def _render_scene_pair(st: Any, state: ImpactToolState) -> None:
    st.markdown("#### Perechea BEFORE / AFTER")

    scene_ids = [scene["ee_id"] for scene in state.scene_candidates]
    labels = {scene["ee_id"]: scene_label(scene) for scene in state.scene_candidates}
    before_id = st.selectbox(
        "Imagine de referință (BEFORE)",
        scene_ids,
        index=_selected_scene_index(scene_ids, state.before_scene, 0),
        format_func=lambda scene_id: labels[scene_id],
        key="impact_before_scene_select",
    )
    after_id = st.selectbox(
        "Imagine după eveniment (AFTER)",
        scene_ids,
        index=_selected_scene_index(
            scene_ids,
            state.after_scene,
            max(0, len(scene_ids) - 1),
        ),
        format_func=lambda scene_id: labels[scene_id],
        key="impact_after_scene_select",
    )
    before, after = select_scene_pair(state.scene_candidates, before_id, after_id)
    selected_pair_changed = (
        (state.before_scene or {}).get("ee_id") not in {None, before_id}
        or (state.after_scene or {}).get("ee_id") not in {None, after_id}
    )
    if selected_pair_changed and state.scene_compare_active:
        reset_comparison(state)
    relative_orbit_mismatch = bool(
        before
        and after
        and before.get("relative_orbit") != after.get("relative_orbit")
    )
    low_coverage = any(
        float((scene or {}).get("coverage_percent") or 0) < 95
        for scene in (before, after)
    )
    state.relative_orbit_override = st.checkbox(
        "Mod experimental: accept orbite relative diferite",
        value=state.relative_orbit_override,
        disabled=not relative_orbit_mismatch,
        help="Nu reprezintă configurația recomandată pentru rularea finală.",
    )
    state.low_coverage_override = st.checkbox(
        "Accept acoperire sub 95% pentru rularea finală",
        value=state.low_coverage_override,
        disabled=not low_coverage,
    )
    if state.relative_orbit_override:
        st.warning(
            "Override experimental activ: orbitele relative diferă. "
            "Rezultatul necesită interpretare prudentă."
        )
    validation = confirm_scene_pair(
        before,
        after,
        allow_relative_orbit_override=state.relative_orbit_override,
        allow_low_coverage_override=state.low_coverage_override,
    )
    for error in validation["errors"]:
        st.error(error)
    for warning in validation["warnings"]:
        st.warning(warning)
    accept_warnings = False
    if st.button(
        "Compară imaginile",
        use_container_width=True,
        disabled=not validation["compatible"],
        key="compare_scene_pair",
    ):
        apply_scene_pair(state, before, after, False)
        state.scene_compare_active = True
        state.swipe_enabled = True
        state.layer_compare_active = False
        _refresh_preview_tiles(state)
        st.rerun()
    if state.swipe_enabled:
        st.caption("Trage direct bara verticală din hartă pentru comparație.")
    if validation["requires_confirmation"]:
        accept_warnings = st.checkbox("Accept avertismentele perechii selectate")
    if st.button(
        "Confirmă imaginile",
        use_container_width=True,
        disabled=not validation["compatible"],
        key="confirm_scene_pair",
    ):
        confirmation = confirm_scene_pair(
            before,
            after,
            accept_warnings,
            allow_relative_orbit_override=state.relative_orbit_override,
            allow_low_coverage_override=state.low_coverage_override,
        )
        state.scene_pair_validation = confirmation
        apply_scene_pair(state, before, after, confirmation["confirmed"])
        if confirmation["confirmed"]:
            state.preview_scene_id = ""
            state.preview_scene_tile = ""
            st.rerun()
    action_left, action_right = st.columns(2)
    if action_left.button(
        "Ieși din comparație",
        use_container_width=True,
        disabled=not state.scene_compare_active,
        key="exit_scene_comparison",
    ):
        reset_comparison(state)
        state.comparison_ready = bool(state.before_scene and state.after_scene)
        st.rerun()
    if action_right.button(
        "Curăță selecția",
        use_container_width=True,
        disabled=not (state.before_scene or state.after_scene),
        key="clear_scene_pair",
    ):
        apply_scene_pair(state, None, None, False)
        st.rerun()


def _render_scene_timeline(st: Any, scenes: list[dict[str, Any]]) -> None:
    entries = timeline_entries(scenes)
    labels = " → ".join(
        f"{entry['date']} ({entry['orbit_pass']})"
        for entry in entries
    )
    st.markdown(
        f'<div class="scene-timeline"><strong>Cronologie</strong><span>{labels}</span></div>',
        unsafe_allow_html=True,
    )


def _render_current_scene(st: Any, state: ImpactToolState) -> None:
    by_id = {
        str(scene.get("ee_id")): scene
        for scene in state.scene_candidates
    }
    current = by_id.get(state.scene_current_id) or state.scene_candidates[0]
    state.scene_current_id = str(current.get("ee_id"))
    image_column, metadata_column = st.columns([2.2, 1.2], gap="large")
    with image_column:
        thumbnail = current.get("thumbnail_url")
        if thumbnail:
            st.image(
                thumbnail,
                caption="Scena Sentinel-1 curentă",
                use_container_width=True,
            )
        else:
            st.warning("Thumbnail indisponibil pentru scena curentă.")
    with metadata_column:
        st.markdown("#### Scena curentă")
        st.write(f"**Data:** {str(current.get('acquisition_time', ''))[:19]}")
        st.write(f"**Orbită:** {current.get('orbit_pass', 'necunoscută')}")
        st.write(f"**Orbită relativă:** {current.get('relative_orbit', 'necunoscută')}")
        st.write(f"**Polarizare:** {current.get('polarization', 'necunoscută')}")
        st.write(
            f"**Acoperire AOI:** {float(current.get('coverage_percent') or 0):.1f}%"
        )
        if st.button(
            "Previzualizează pe hartă",
            key="preview-current-scene",
            use_container_width=True,
        ):
            _preview_scene(state, current)
            st.rerun()
        before_column, after_column = st.columns(2)
        if before_column.button(
            "Alege BEFORE",
            key="choose-current-before",
            use_container_width=True,
        ):
            apply_scene_pair(state, current, state.after_scene, False)
            st.rerun()
        if after_column.button(
            "Alege AFTER",
            key="choose-current-after",
            use_container_width=True,
        ):
            apply_scene_pair(state, state.before_scene, current, False)
            st.rerun()


def _render_scene_gallery(st: Any, state: ImpactToolState) -> None:
    st.markdown("##### Galerie scene")
    visible_scenes = state.scene_candidates[: state.scene_gallery_limit]
    for row_start in range(0, len(visible_scenes), 4):
        columns = st.columns(4)
        for column, scene in zip(
            columns,
            visible_scenes[row_start : row_start + 4],
        ):
            with column:
                thumbnail = scene.get("thumbnail_url")
                if thumbnail:
                    st.image(thumbnail, use_container_width=True)
                else:
                    st.caption("Thumbnail indisponibil")
                st.caption(
                    f"{str(scene.get('acquisition_time', ''))[:16].replace('T', ' ')}\n\n"
                    f"{scene.get('orbit_pass', '?')} · orbita "
                    f"{scene.get('relative_orbit', '?')} · "
                    f"{scene.get('polarization', '?')} · "
                    f"{float(scene.get('coverage_percent') or 0):.1f}% AOI"
                )
                scene_id = str(scene.get("ee_id"))
                if st.button(
                    "Scenă curentă",
                    key=f"preview-scene-{scene_id}",
                    use_container_width=True,
                ):
                    state.scene_current_id = scene_id
                    st.rerun()
                before_col, after_col = st.columns(2)
                if before_col.button(
                    "Alege BEFORE",
                    key=f"choose-before-{scene_id}",
                    use_container_width=True,
                ):
                    apply_scene_pair(state, scene, state.after_scene, False)
                    st.session_state["impact_before_scene_select"] = scene_id
                    st.rerun()
                if after_col.button(
                    "Alege AFTER",
                    key=f"choose-after-{scene_id}",
                    use_container_width=True,
                ):
                    apply_scene_pair(state, state.before_scene, scene, False)
                    st.session_state["impact_after_scene_select"] = scene_id
                    st.rerun()
    if state.scene_gallery_limit < len(state.scene_candidates):
        if st.button(
            "Afișează mai multe",
            use_container_width=True,
            key="show_more_scene_thumbnails",
        ):
            _load_more_thumbnails(state)
            st.rerun()


def _preview_scene(state: ImpactToolState, scene: dict[str, Any]) -> None:
    gee = initialize_earth_engine()
    if not gee.available or gee.ee is None:
        state.scene_errors = [gee.message]
        return
    aoi = build_aoi_from_geometry(gee.ee, state.active_geometry, state.active_area_bbox)
    state.preview_scene_id = str(scene.get("ee_id"))
    state.preview_scene_tile = preview_tile_for_scene(gee.ee, aoi, scene)


def _selected_scene_index(
    scene_ids: list[str],
    selected: dict[str, Any] | None,
    fallback: int,
) -> int:
    selected_id = (selected or {}).get("ee_id")
    return scene_ids.index(selected_id) if selected_id in scene_ids else fallback


def _refresh_preview_tiles(state: ImpactToolState) -> None:
    if not state.before_scene or not state.after_scene:
        return
    gee = initialize_earth_engine()
    if not gee.available or gee.ee is None:
        state.scene_errors = [gee.message]
        return
    aoi = build_aoi_from_geometry(gee.ee, state.active_geometry, state.active_area_bbox)
    state.preview_tiles = preview_tiles_for_pair(
        gee.ee,
        aoi,
        state.before_scene,
        state.after_scene,
        state.preview_mode,
        threshold=float(state.analysis_parameters["water_threshold"]),
        smoothing_meters=int(state.analysis_parameters["smoothing_meters"]),
        minimum_connected_pixels=int(
            state.analysis_parameters["minimum_connected_pixels"]
        ),
    )
    state.scene_compare_tiles = dict(state.preview_tiles)


def _load_more_thumbnails(state: ImpactToolState) -> None:
    gee = initialize_earth_engine()
    if not gee.available or gee.ee is None:
        state.scene_errors = [gee.message]
        return
    state.scene_gallery_limit = min(
        len(state.scene_candidates),
        state.scene_gallery_limit + 8,
    )
    aoi = build_aoi_from_geometry(gee.ee, state.active_geometry, state.active_area_bbox)
    state.scene_candidates, _ = hydrate_scene_thumbnails(
        cache=PersistentCache(),
        ee=gee.ee,
        aoi=aoi,
        aoi_hash=state.active_area_hash,
        scenes=state.scene_candidates,
        max_thumbnails=state.scene_gallery_limit,
    )

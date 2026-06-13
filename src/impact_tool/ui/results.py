from __future__ import annotations

from typing import Any

from src.impact_tool.analysis import recalculate_osm_impact
from src.impact_tool.final_export import export_final_run_package
from src.impact_tool.models import TAB_NAMES, ImpactToolState
from src.impact_tool.state import reset_analysis_results, reset_scene_selection
from src.impact_tool.sar_qa import sar_qa_chart_data


def render_result_tabs(st: Any, state: ImpactToolState) -> None:
    tabs = st.tabs(list(TAB_NAMES))
    with tabs[0]:
        st.info("Harta principală rămâne spațiul central de lucru.")
        _render_map_tools(st, state)
        if state.cache_events:
            with st.expander("Jurnal procesare și cache", expanded=False):
                for event in state.cache_events[-12:]:
                    st.caption(f"✓ {event}")
                if state.timings:
                    st.json(state.timings, expanded=False)
    with tabs[1]:
        _render_summary(st, state)
    with tabs[2]:
        impact = state.analysis_results.get("osm_impact")
        if impact:
            _render_priority_table(st, state, impact)
        else:
            st.info("Elementele expuse vor fi disponibile după analiza OSM.")
    with tabs[3]:
        _render_sar_summary(st, state)
        _render_dynamic_world(st, state)
        _render_osm(st, state)
    with tabs[4]:
        st.info("Raportul final devine disponibil după finalizarea analizei.")
        pdf_validation = state.analysis_results.get("pdf_validation")
        if pdf_validation:
            if pdf_validation.get("status") == "disponibil":
                st.success(
                    "PDF validat local: "
                    f"{pdf_validation.get('page_count')} pagini, "
                    f"{pdf_validation.get('size_bytes')} bytes."
                )
            else:
                st.error(
                    pdf_validation.get("error")
                    or "Validarea structurală PDF a eșuat."
                )
        if st.button(
            "Exportă pachetul tehnic al rulării",
            disabled=not state.analysis_complete,
            key="export_final_run_package",
        ):
            paths = export_final_run_package(state)
            st.success("Pachetul tehnic al rulării a fost exportat.")
            for label, path in paths.items():
                st.caption(f"{label}: {path}")


def _render_summary(st: Any, state: ImpactToolState) -> None:
    sar = state.analysis_results.get("sar") or {}
    sar_metrics = sar.get("metrics", {})
    dynamic = state.analysis_results.get("dynamic_world") or {}
    dynamic_metrics = dynamic.get("metric_values", {})
    impact = state.analysis_results.get("osm_impact") or {}
    osm_metrics = impact.get("metrics", {})
    primary = (
        ("Apă nouă evidențiată SAR", _metric_value(sar_metrics.get("sar_new_water_area_km2")), "km²"),
        (
            "Suprapunere SAR × Dynamic World",
            dynamic_metrics.get("sar_dynamic_world_new_water_overlap_area_km2"),
            "km²",
        ),
        ("Clădiri direct intersectate", osm_metrics.get("buildings_direct"), ""),
        ("Clădiri în buffer", osm_metrics.get("buildings_buffer"), ""),
        (
            "Drumuri afectate",
            float(osm_metrics.get("roads_direct_km") or 0)
            + float(osm_metrics.get("roads_buffer_km") or 0),
            "km",
        ),
        (
            "Obiective importante direct / buffer",
            f"{osm_metrics.get('critical_direct', 0)} / {osm_metrics.get('critical_buffer', 0)}",
            "",
        ),
    )
    for start in range(0, len(primary), 3):
        columns = st.columns(3)
        for column, (label, value, unit) in zip(columns, primary[start : start + 3]):
            if value is None:
                column.metric(label, "indisponibil")
            elif isinstance(value, str):
                column.metric(label, value)
            elif unit:
                column.metric(label, f"{float(value):.3f} {unit}")
            else:
                column.metric(label, str(int(value)))

    with st.expander("Indicatori secundari", expanded=False):
        st.write(
            {
                "Apă BEFORE (km²)": _metric_value(
                    sar_metrics.get("sar_water_before_area_km2")
                ),
                "Apă AFTER (km²)": _metric_value(
                    sar_metrics.get("sar_water_after_area_km2")
                ),
                "Căi ferate direct (km)": osm_metrics.get("railways_direct_km"),
                "Poduri direct": osm_metrics.get("bridges_direct"),
                "Completitudine OSM": _osm_completeness(state.osm_status),
                "Timpi (s)": state.timings,
            }
        )

    st.markdown("#### Calitatea datelor")
    quality = st.columns(4)
    quality[0].caption("SAR: disponibil" if sar else "SAR: indisponibil")
    quality[1].caption(
        "Dynamic World: disponibil"
        if dynamic.get("status") == "reușit"
        else "Dynamic World: avertisment"
    )
    important = state.external_api_status.get("important_features", {})
    quality[2].caption(
        "Obiective: " + str(important.get("source") or "indisponibil")
    )
    quality[3].caption(
        "OSM țintit: " + _osm_completeness(state.osm_status)
    )


def _metric_value(metric: Any) -> float | None:
    if isinstance(metric, dict):
        if metric.get("status") != "reușit":
            return None
        metric = metric.get("value")
    return float(metric) if metric is not None else None


def _osm_completeness(statuses: dict[str, dict[str, Any]]) -> str:
    if not statuses:
        return "indisponibil"
    values = {status.get("completeness") for status in statuses.values()}
    return "complet" if values == {"complet"} else "parțial"


def _render_sar_summary(st: Any, state: ImpactToolState) -> None:
    sar = state.analysis_results.get("sar")
    if not sar:
        st.info("Indicatorii de impact vor fi disponibili după analiză.")
        return
    metrics = sar.get("metrics", {})
    columns = st.columns(3)
    _render_sar_metric(columns[0], "Apă BEFORE", metrics.get("sar_water_before_area_km2"))
    _render_sar_metric(columns[1], "Apă AFTER", metrics.get("sar_water_after_area_km2"))
    _render_sar_metric(columns[2], "Apă nouă SAR", metrics.get("sar_new_water_area_km2"))
    tiles = sar.get("tiles", {})
    vectorization = sar.get("vectorization", {})
    status_columns = st.columns(4)
    status_columns[0].caption(
        "Raster SAR: "
        + ("disponibil" if any(item.get("status") == "reușit" for item in tiles.values()) else "indisponibil")
    )
    status_columns[1].caption(
        "Metrici: "
        + ("disponibile" if metrics and all(item.get("status") == "reușit" for item in metrics.values()) else "indisponibile")
    )
    status_columns[2].caption(
        "Vectorizare: "
        + ("disponibilă" if vectorization.get("status") == "reușit" else "indisponibilă")
    )
    status_columns[3].caption(
        "Impact OSM: "
        + ("disponibil" if state.analysis_results.get("osm_impact") else "indisponibil")
    )
    diagnostics = [
        {"component": layer_id, **status}
        for layer_id, status in tiles.items()
        if status.get("status") != "reușit"
    ]
    if vectorization.get("status") == "eroare":
        diagnostics.append({"component": "vectorizare", **vectorization})
    if diagnostics:
        with st.expander("Diagnostic SAR", expanded=True):
            st.json(diagnostics, expanded=False)
    if st.button(
        "Rulează analiza de sensibilitate SAR (QA)",
        disabled=not state.analysis_complete,
        key="run_sar_qa",
    ):
        state.sar_qa_requested = True
        st.rerun()
    qa = state.analysis_results.get("sar_qa")
    if qa:
        st.markdown("#### QA prag SAR")
        st.dataframe(qa.get("rows", []), use_container_width=True, hide_index=True)
        chart_data = sar_qa_chart_data(qa)
        if chart_data:
            st.line_chart(chart_data)
        else:
            st.warning("Graficul QA nu este disponibil deoarece metricile lipsesc.")
        with st.expander("Checklist manual QA", expanded=False):
            for item in qa.get("manual_checklist", []):
                st.checkbox(item, key=f"sar-qa-check-{item}")
    elif state.analysis_results.get("sar_qa_error"):
        st.warning(state.analysis_results["sar_qa_error"])
    st.caption(f"Durata procesării SAR: {sar.get('duration_seconds', 0):.2f} s")


def _render_sar_metric(container: Any, label: str, metric: Any) -> None:
    if isinstance(metric, dict) and metric.get("status") == "reușit":
        container.metric(label, f"{float(metric.get('value')):.3f} km²")
        return
    error = metric.get("error") if isinstance(metric, dict) else "metrică indisponibilă"
    container.metric(label, "indisponibil")
    container.caption(error or "metrică indisponibilă")


def _render_dynamic_world(st: Any, state: ImpactToolState) -> None:
    if st.button(
        "Rulează / Reîncearcă Dynamic World",
        disabled=not bool(state.analysis_results.get("sar")),
        key="run_dynamic_world",
    ):
        state.dynamic_world_requested = True
        st.rerun()
    result = state.analysis_results.get("dynamic_world")
    if not result:
        message = state.analysis_results.get(
            "dynamic_world_error",
            "Rezultatele Dynamic World vor fi disponibile după analiză.",
        )
        st.info(message)
        return
    status = result.get("status", "indisponibil")
    if status == "reușit":
        st.success("Dynamic World: reușit")
    elif status == "tile indisponibil":
        st.warning(result.get("error") or "Dynamic World: tile indisponibil")
    else:
        st.error(result.get("error") or f"Dynamic World: {status}")
    periods = result.get("periods", {})
    dates = result.get("acquisition_dates", {})
    product_types = result.get("product_types", {})
    coverage = result.get("coverage", {})
    st.caption(
        f"Sursă: {result.get('source', 'Google Dynamic World V1')} | "
        f"durată: {float(result.get('duration_seconds') or state.timings.get('Dynamic World', 0)):.2f} s"
    )
    st.caption(
        "BEFORE: "
        f"căutare {periods.get('before')} · data efectivă {dates.get('before')} · "
        f"acoperire {_coverage_label(coverage.get('before'))} · "
        f"{product_types.get('before') or 'produs indisponibil'}"
    )
    st.caption(
        "AFTER: "
        f"căutare {periods.get('after')} · data efectivă {dates.get('after')} · "
        f"acoperire {_coverage_label(coverage.get('after'))} · "
        f"{product_types.get('after') or 'produs indisponibil'}"
    )
    tile_errors = {
        key: value
        for key, value in result.get("tiles", {}).items()
        if isinstance(value, dict) and value.get("status") != "reușit"
    }
    if tile_errors:
        with st.expander("Diagnostic tile-uri Dynamic World", expanded=False):
            st.json(tile_errors, expanded=False)
    st.subheader("Diferențe observate Dynamic World")
    st.bar_chart(result.get("transition_values", {}))
    metric_values = result.get("metric_values", {})
    metric_columns = st.columns(3)
    _render_optional_metric(
        metric_columns[0],
        "Suprapunere SAR × Dynamic World",
        metric_values.get("sar_dynamic_world_new_water_overlap_area_km2"),
    )
    _render_optional_metric(
        metric_columns[1],
        "Apă nouă doar SAR",
        metric_values.get("new_water_only_sar_area_km2"),
    )
    _render_optional_metric(
        metric_columns[2],
        "Apă nouă doar Dynamic World",
        metric_values.get("new_water_only_dynamic_world_area_km2"),
    )
    osm_correlation = state.analysis_results.get("osm_dynamic_world") or {}
    st.markdown("#### Corelare OSM × Dynamic World")
    if osm_correlation.get("rows"):
        st.dataframe(
            osm_correlation["rows"],
            use_container_width=True,
            hide_index=True,
        )
    elif osm_correlation.get("error"):
        st.warning(osm_correlation["error"])
    else:
        st.caption("Corelarea OSM × Dynamic World nu are rezultate disponibile.")


def _render_osm(st: Any, state: ImpactToolState) -> None:
    if not state.analysis_complete:
        st.info("Elementele OSM pot fi încărcate numai după analiza SAR.")
        return
    action_columns = st.columns(3)
    if action_columns[0].button(
        "Încarcă obiective importante",
        key="load_important_features",
    ):
        state.important_features_requested = True
        st.rerun()
    if action_columns[1].button(
        "Analizează impactul OSM",
        key="run_targeted_osm",
        disabled=not bool(
            state.analysis_results.get("sar", {}).get("new_water_geometry")
        ),
    ):
        state.osm_impact_requested = True
        state.osm_load_requested = True
        st.rerun()
    if action_columns[2].button(
        "Recalculează impactul pentru noul buffer",
        key="recalculate_osm_buffer",
        disabled=not bool(state.analysis_results.get("osm_raw")),
    ):
        recalculate_osm_impact(state)
        st.rerun()
    if not state.osm_status:
        st.caption(
            "Datele externe sunt opționale și se încarcă numai la cererea utilizatorului."
        )
        status = state.external_api_status.get("important_features", {})
        if status.get("warning"):
            st.warning(status["warning"])
        return
    overpass_status = state.external_api_status.get("overpass", {})
    st.markdown("#### Disponibilitate API și domeniul analizei")
    st.caption(
        f"Overpass: {'disponibil' if overpass_status.get('ok') else 'indisponibil'} · "
        f"buffer: {state.buffer_meters} m · "
        f"ultima rulare: {overpass_status.get('last_run', 'indisponibilă')} · "
        f"durată: {float(overpass_status.get('duration_seconds') or 0):.2f} s"
    )
    if overpass_status.get("warning"):
        st.warning(overpass_status["warning"])
    st.info(f"Sursa OSM: {_osm_source_label(state.osm_status)}")
    for category, status in state.osm_status.items():
        if status.get("ok"):
            st.caption(
                f"Sursa: {status.get('source', 'necunoscută')} | "
                f"ultima rulare: {status.get('last_run', 'indisponibilă')} | "
                f"completitudine: {status.get('completeness', 'necunoscută')} | "
                f"durată: {float(status.get('duration_seconds') or 0):.2f} s"
            )
            st.success(
                f"{category}: {status.get('display_features', status.get('parsed_features', 0))} "
                f"obiecte afișate · {status.get('source')}"
            )
            for warning in status.get("warnings", []):
                st.warning(warning)
        else:
            st.warning(
                f"{category}: "
                f"{status.get('warning') or status.get('error', 'eroare necunoscută')}"
            )
    impact = state.analysis_results.get("osm_impact")
    if impact:
        status_counts = impact.get("metrics", {}).get("status_counts", {})
        if status_counts:
            st.dataframe(
                [
                    {"clasă expunere": label, "elemente": count}
                    for label, count in status_counts.items()
                ],
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Mod QA", expanded=False):
            st.caption("Informații tehnice pentru verificarea implementării.")
            st.json(
                {
                    "counts": impact.get("metrics", {}).get("status_counts", {}),
                    "cache": state.osm_status,
                    "events": state.cache_events[-10:],
                    "relations_omise": sum(
                        len(status.get("warnings", []))
                        for status in state.osm_status.values()
                    ),
                },
                expanded=False,
            )
    else:
        st.warning(
            "Impactul geometric necesită geometria vectorială a apei noi SAR; "
            "datele OSM brute rămân disponibile."
        )


def _osm_source_label(statuses: dict[str, dict[str, Any]]) -> str:
    sources = {
        str(status.get("source", "")).strip().lower()
        for status in statuses.values()
        if status.get("ok")
    }
    if not sources:
        return "indisponibila"
    if sources <= {"cache"}:
        return "cache local"
    if any("overpass" in source for source in sources):
        return "descarcare live Overpass API"
    return ", ".join(sorted(sources))


def _coverage_label(value: Any) -> str:
    if value is None:
        return "indisponibilă"
    return f"{float(value) * 100:.1f}%"


def _render_optional_metric(
    container: Any,
    label: str,
    value: Any,
    unit: str = "km²",
) -> None:
    if value is None:
        container.metric(label, "indisponibil")
        return
    container.metric(label, f"{float(value):.3f} {unit}")


def _render_priority_table(st: Any, state: ImpactToolState, impact: dict[str, Any]) -> None:
    rows = []
    category_names = {
        "osm_buildings": "Clădire",
        "osm_roads": "Drum",
        "osm_railways": "Cale ferată",
        "osm_bridges": "Pod",
        "osm_critical": "Obiectiv critic",
    }
    for layer_id, layer in impact.get("layers", {}).items():
        for feature in layer.get("features", []):
            properties = feature.get("properties", {})
            if properties.get("status") == "Neexpus":
                continue
            point = _feature_center(feature.get("geometry") or {})
            rows.append(
                {
                    "name": properties.get("name") or "Fără nume",
                    "category": category_names.get(layer_id, layer_id),
                    "status": properties.get("status", "Necunoscut"),
                    "distance_to_water_m": properties.get("distance_to_water_m", 0),
                    "level": properties.get("infrastructure_level", "context tehnic"),
                    "locality": properties.get("locality") or properties.get("city") or "",
                    "source": properties.get("source") or "OpenStreetMap",
                    "coordinates": point,
                }
            )
    priority = {"esențial": 0, "important": 1, "context tehnic": 2}
    filter_label = st.selectbox(
        "Filtru elemente",
        ["Toate expuse", "Direct", "Buffer", "Obiective importante"],
        key="osm_result_filter",
    )
    if filter_label == "Direct":
        rows = [row for row in rows if "direct" in row["status"].lower()]
    elif filter_label == "Buffer":
        rows = [row for row in rows if "buffer" in row["status"].lower()]
    elif filter_label == "Obiective importante":
        rows = [
            row for row in rows
            if row["category"] == "Obiectiv critic"
        ]
    rows.sort(
        key=lambda row: (
            priority.get(row["level"], 3),
            row["distance_to_water_m"],
        )
    )
    st.markdown("#### Elemente potențial expuse")
    st.dataframe(
        [
            {
                "Nume": row["name"],
                "Tip": row["category"],
                "Expunere": row["status"],
                "Distanță până la apă": row["distance_to_water_m"],
                "Localitate": row["locality"],
                "Sursă": row["source"],
            }
            for row in rows[:250]
        ],
        use_container_width=True,
        hide_index=True,
    )
    if rows:
        labels = {
            f"{row['name']} · {row['category']} · {index + 1}": row
            for index, row in enumerate(rows[:250])
        }
        selected = st.selectbox(
            "Element pentru centrare",
            list(labels),
            key="osm_selected_feature",
        )
        if st.button("Centrează elementul selectat", key="osm_center_selected"):
            state.map_focus = labels[selected]["coordinates"]
            st.rerun()


def _feature_center(geometry: dict[str, Any]) -> list[float]:
    from shapely.geometry import shape

    point = shape(geometry).representative_point()
    return [point.y, point.x]


def _render_map_tools(st: Any, state: ImpactToolState) -> None:
    with st.expander("Instrumente și resetare", expanded=False):
        st.caption(
            "Harta include identificarea coordonatelor, măsurarea distanței și suprafeței, "
            "revenire la România, centrare pe județ și ecran complet."
        )
        columns = st.columns(3)
        if columns[0].button("Curăță scenele", key="clear_all_scenes"):
            reset_scene_selection(state)
            st.rerun()
        if columns[1].button("Curăță rezultatele", key="clear_analysis_results"):
            reset_analysis_results(state)
            st.rerun()
        if columns[2].button(
            "Reia analiza",
            disabled=not state.scenes_confirmed,
            key="rerun_analysis",
        ):
            state.run_requested = True
            st.rerun()

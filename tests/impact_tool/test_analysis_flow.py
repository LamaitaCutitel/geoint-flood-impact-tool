from __future__ import annotations

from src.impact_tool import analysis
from src.impact_tool.models import ImpactToolState


class FakeGeeStatus:
    available = True
    ee = object()


def _analysis_state() -> ImpactToolState:
    return ImpactToolState(
        active_area_hash="area",
        active_area_bbox=[27, 45, 28, 46],
        county_geometry={"type": "Polygon", "coordinates": []},
        before_scene={"ee_id": "before"},
        after_scene={"ee_id": "after"},
        scenes_confirmed=True,
    )


def _mock_raster_dependencies(monkeypatch, dynamic_calls: list[str]) -> None:
    monkeypatch.setattr(analysis, "initialize_earth_engine", lambda: FakeGeeStatus())
    monkeypatch.setattr(analysis, "build_aoi_from_geometry", lambda *args: "aoi")
    monkeypatch.setattr(
        analysis,
        "run_sar_analysis",
        lambda *args: {
            "products": {"sar_new_water": "water"},
            "duration_seconds": 0.2,
            "vectorization_duration_seconds": 0.1,
        },
    )
    monkeypatch.setattr(
        analysis,
        "run_dynamic_world_analysis",
        lambda *args: dynamic_calls.append("dynamic") or {"metrics": {}},
    )


def test_sar_analysis_reports_progress_without_external_calls(monkeypatch) -> None:
    state = _analysis_state()
    osm_calls: list[str] = []
    dynamic_calls: list[str] = []
    _mock_raster_dependencies(monkeypatch, dynamic_calls)
    monkeypatch.setattr(
        analysis,
        "execute_osm_loading",
        lambda state, progress_callback=None, **kwargs: osm_calls.append("osm") or True,
    )

    progress = []
    assert analysis.execute_analysis(
        state,
        mode="rapid",
        progress_callback=lambda percent, stage: progress.append((percent, stage)),
    )

    assert osm_calls == []
    assert dynamic_calls == []
    assert progress[-1] == (100, "Analiza SAR a fost finalizată")
    assert state.analysis_progress == 100
    assert state.active_layers == ["sar_new_water", "buffer"]
    assert state.timings["SAR"] == 0.2
    assert state.timings["vectorizare"] == 0.1
    assert any(event.startswith("Timp SAR:") for event in state.cache_events)


def test_dynamic_world_remains_explicit_after_sar(monkeypatch) -> None:
    state = _analysis_state()
    dynamic_calls: list[str] = []
    _mock_raster_dependencies(monkeypatch, dynamic_calls)
    monkeypatch.setattr(analysis, "execute_osm_loading", lambda *args, **kwargs: True)

    assert analysis.execute_analysis(state, mode="detaliat")
    assert dynamic_calls == []
    assert "dynamic_world" not in state.analysis_results


def test_complete_analysis_preserves_sar_when_optional_stages_fail(monkeypatch) -> None:
    state = _analysis_state()
    dynamic_calls: list[str] = []
    _mock_raster_dependencies(monkeypatch, dynamic_calls)
    monkeypatch.setattr(analysis, "execute_dynamic_world", lambda *args, **kwargs: False)
    monkeypatch.setattr(analysis, "execute_important_features", lambda *args, **kwargs: False)
    monkeypatch.setattr(analysis, "execute_osm_loading", lambda *args, **kwargs: False)

    progress = []
    assert analysis.execute_complete_analysis(
        state,
        progress_callback=lambda percent, stage: progress.append((percent, stage)),
    )

    assert state.analysis_complete is True
    assert state.analysis_results["workflow_status"] == "parțial"
    assert progress[-1] == (100, "Analiza completă s-a încheiat")


def test_sar_workflow_is_complete_before_osm(monkeypatch) -> None:
    state = _analysis_state()
    dynamic_calls: list[str] = []
    _mock_raster_dependencies(monkeypatch, dynamic_calls)
    monkeypatch.setattr(analysis, "execute_osm_loading", lambda *args, **kwargs: False)

    assert analysis.execute_analysis(state, mode="rapid")
    assert state.analysis_results["sar_status"]["osm_impact_available"] is False
    assert state.analysis_results["workflow_status"] == "sar_reușit"


def test_manual_dynamic_world_invalidates_pdf_and_recalculates_correlation(
    monkeypatch,
) -> None:
    state = _analysis_state()
    state.analysis_results = {
        "sar": {"products": {"sar_new_water": "water"}},
        "osm_impact": {"layers": {}},
    }
    state.report_bytes = b"old"
    state.report_filename = "old.pdf"
    monkeypatch.setattr(analysis, "initialize_earth_engine", lambda: FakeGeeStatus())
    monkeypatch.setattr(analysis, "build_aoi_from_geometry", lambda *args: "aoi")
    monkeypatch.setattr(
        analysis,
        "run_dynamic_world_analysis",
        lambda *args: {"status": "reușit", "metrics": {}},
    )
    monkeypatch.setattr(
        analysis,
        "correlate_osm_dynamic_world",
        lambda *args: {"status": "reușit", "rows": [{"name": "Spital"}]},
    )

    assert analysis.execute_dynamic_world(state)
    assert state.report_bytes is None
    assert state.report_filename == ""
    assert state.analysis_results["osm_dynamic_world"]["rows"]


def test_osm_loading_uses_targeted_water_geometry(monkeypatch) -> None:
    state = ImpactToolState(
        analysis_complete=True,
        analysis_mode="rapid",
        active_area_hash="area",
        county_geometry={
            "type": "Polygon",
            "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 45]]],
        },
        analysis_results={
            "sar": {
                "new_water_geometry": {
                    "type": "Polygon",
                    "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 45]]],
                }
            }
        },
    )
    captured = {}
    monkeypatch.setattr(
        analysis,
        "fetch_targeted_impact",
        lambda **kwargs: captured.update(kwargs)
        or type(
            "Result",
            (),
            {
                "data": {"categories": {}, "metadata": {"element_count": 0}},
                "status": type(
                    "Status",
                    (),
                    {
                        "ok": True,
                        "source": "test",
                        "completeness": "complet",
                        "duration_seconds": 0,
                        "warning": "",
                    },
                )(),
            },
        )(),
    )
    monkeypatch.setattr(analysis, "build_osm_geojson_layers", lambda elements: {})
    monkeypatch.setattr(analysis, "recalculate_osm_impact", lambda *args: True)

    assert analysis.execute_osm_loading(state)
    assert captured["water_geometry"] == state.analysis_results["sar"]["new_water_geometry"]
    assert captured["buffer_meters"] == 250


def test_osm_impact_uses_operational_sar_geometry(monkeypatch) -> None:
    operational = {
        "type": "Polygon",
        "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 45]]],
    }
    display = {
        "type": "Polygon",
        "coordinates": [[[27.1, 45.1], [27.9, 45.1], [27.9, 45.9], [27.1, 45.1]]],
    }
    state = ImpactToolState(
        analysis_complete=True,
        county_geometry=operational,
        analysis_results={
            "sar": {
                "new_water_geometry": operational,
                "new_water_display_geometry": display,
            },
            "osm_raw": {
                "layers": {
                    "osm_roads": {"type": "FeatureCollection", "features": []}
                }
            },
        },
    )
    captured = {}
    monkeypatch.setattr(
        analysis,
        "classify_osm_impact",
        lambda layers, water_geometry, *args, **kwargs: captured.setdefault(
            "water",
            water_geometry,
        )
        or {"layers": {}, "metrics": {}},
    )

    assert analysis.recalculate_osm_impact(state)
    assert captured["water"] == operational


def test_osm_complete_requires_ok_and_complete_for_every_category() -> None:
    assert analysis._osm_load_status(
        {
            "buildings": {"ok": True, "completeness": "complet"},
            "roads": {"ok": True, "completeness": "complet"},
        }
    ) == "osm_complet"
    assert analysis._osm_load_status(
        {
            "buildings": {"ok": True, "completeness": "complet"},
            "roads": {"ok": True, "completeness": "posibil incomplet"},
        }
    ) == "osm_parțial"
    assert analysis._osm_load_status(
        {
            "buildings": {"ok": False, "error": "timeout"},
            "roads": {"ok": False, "error": "timeout"},
        }
    ) == "osm_indisponibil"


def test_osm_partial_reasons_name_category_and_cause() -> None:
    reasons = analysis._osm_partial_reasons(
        {
            "roads": {"ok": True, "completeness": "posibil incomplet"},
            "bridges": {"ok": False, "error": "timeout Overpass"},
        }
    )
    assert "roads: completitudine posibil incomplet" in reasons
    assert "bridges: timeout Overpass" in reasons

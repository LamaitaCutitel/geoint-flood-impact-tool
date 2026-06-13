from __future__ import annotations

from pathlib import Path

from src.impact_tool.cache import PersistentCache
from src.impact_tool.models import ImpactToolState
from src.impact_tool.report import (
    MANDATORY_NOTE,
    _chart_datasets,
    _dynamic_world_tile_summary,
    generate_cached_report,
    generate_report_pdf,
    report_filename,
    save_report_pdf,
    _metric_label,
    _osm_dynamic_world_summary,
    _report_cache_key,
    _real_scale_bar,
    _osm_status_table,
    _synthetic_map,
    validate_report_pdf,
)


def _state() -> ImpactToolState:
    return ImpactToolState(
        county_name="Galati",
        active_area_km2=100,
        analysis_complete=True,
        analysis_hash="analysis",
        after_scene={"acquisition_time": "2024-09-14T10:00:00Z"},
        before_scene={
            "acquisition_time": "2024-09-01T10:00:00Z",
            "polarization": "VH",
            "orbit_pass": "ASCENDING",
        },
        analysis_results={
            "sar": {
                "metrics": {
                    "sar_water_before_area_km2": 1,
                    "sar_water_after_area_km2": 3,
                    "sar_new_water_area_km2": 2,
                },
                "duration_seconds": 1.2,
            }
        },
    )


def test_pdf_is_generated_with_partial_results() -> None:
    pdf = generate_report_pdf(_state())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 20_000
    validation = validate_report_pdf(pdf)
    assert validation["status"] == "disponibil"
    assert validation["page_count"] > 0
    assert validation["mandatory_note_present"]
    assert validation["tables_and_charts_present"]


def test_pdf_supports_aoi_and_buffer_extremes() -> None:
    state = _state()
    state.aoi_geometry = {
        "type": "Polygon",
        "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 46], [27, 45]]],
    }
    state.buffer_meters = 1
    assert generate_report_pdf(state).startswith(b"%PDF")
    state.buffer_meters = 1000
    assert generate_report_pdf(state).startswith(b"%PDF")


def test_report_cache(tmp_path) -> None:
    cache = PersistentCache(tmp_path)
    first, first_hit = generate_cached_report(_state(), cache)
    second, second_hit = generate_cached_report(_state(), cache)
    assert not first_hit
    assert second_hit
    assert first == second


def test_report_cache_key_changes_with_full_payload(tmp_path) -> None:
    cache = PersistentCache(tmp_path)
    state = _state()
    initial = _report_cache_key(cache, state)
    state.analysis_mode = "detaliat"
    detailed = _report_cache_key(cache, state)
    state.osm_status = {"roads": {"cache_date": "2026-06-12", "count": 1}}
    osm_changed = _report_cache_key(cache, state)
    state.analysis_results["dynamic_world"] = {
        "acquisition_dates": {"before": "2024-09-01", "after": "2024-09-15"}
    }
    dynamic_changed = _report_cache_key(cache, state)
    assert len({initial, detailed, osm_changed, dynamic_changed}) == 4


def test_report_cache_key_changes_after_analytic_recalculation(tmp_path) -> None:
    cache = PersistentCache(tmp_path)
    state = _state()
    initial = _report_cache_key(cache, state)
    state.analysis_results["sar"]["metrics"]["sar_new_water_area_km2"] = 4.25
    recalculated = _report_cache_key(cache, state)
    assert initial != recalculated


def test_report_has_readable_labels_and_osm_completeness() -> None:
    state = _state()
    state.osm_status = {
        "buildings": {
            "count": 12,
            "source": "cache",
            "cache_date": "2026-06-11T10:00:00Z",
            "completeness": "complet",
        }
    }
    assert _metric_label("roads_direct_km") == "Drumuri intersectate direct (km)"
    assert len(_osm_status_table(state)._cellvalues) == 2


def test_synthetic_map_contains_osm_and_works_offline() -> None:
    state = _state()
    state.county_geometry = {
        "type": "Polygon",
        "coordinates": [[[27, 45], [28, 45], [28, 46], [27, 46], [27, 45]]],
    }
    state.analysis_results["sar"]["new_water_geometry"] = {
        "type": "Polygon",
        "coordinates": [[[27.4, 45.4], [27.6, 45.4], [27.6, 45.6], [27.4, 45.6], [27.4, 45.4]]],
    }
    state.analysis_results["osm_impact"] = {
        "buffer_geometry": state.analysis_results["sar"]["new_water_geometry"],
        "metrics": {"roads_direct_km": 1.2},
        "layers": {
            "osm_roads": {
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[27.3, 45.5], [27.7, 45.5]],
                        },
                        "properties": {"status": "Intersectat direct"},
                    }
                ]
            },
            "osm_critical": {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [27.5, 45.5]},
                        "properties": {"status": "Intersectat direct"},
                    }
                ]
            },
        },
    }
    image = _synthetic_map(state)
    assert image.read(8) == b"\x89PNG\r\n\x1a\n"
    assert len(image.getvalue()) > 10_000


def test_map_scale_is_geodetic_and_report_has_no_raw_parameter_dict() -> None:
    width, label = _real_scale_bar(27.0, 28.0, 45.5)
    assert 0 < width < 1
    assert label.endswith(("m", "km"))
    source = Path("src/impact_tool/report.py").read_text(encoding="utf-8")
    assert "str(state.analysis_parameters)" not in source


def test_synthetic_map_uses_clipped_geometry_for_lines(monkeypatch) -> None:
    from src.impact_tool import report

    state = _state()
    original = {
        "type": "LineString",
        "coordinates": [[27.0, 45.0], [28.0, 46.0]],
    }
    clipped = {
        "type": "LineString",
        "coordinates": [[27.4, 45.4], [27.6, 45.6]],
    }
    state.analysis_results["osm_impact"] = {
        "layers": {
            "osm_roads": {
                "features": [
                    {
                        "geometry": original,
                        "clipped_geometry": clipped,
                        "properties": {"status": "Intersectat direct"},
                    }
                ]
            }
        }
    }
    plotted = []
    monkeypatch.setattr(
        report,
        "_plot_osm_feature",
        lambda axis, geometry, color, width, alpha: plotted.append(geometry),
    )
    report._synthetic_map(state)
    assert clipped in plotted
    assert original not in plotted


def test_chart_datasets_do_not_mix_units() -> None:
    state = _state()
    state.analysis_results["osm_impact"] = {
        "metrics": {
            "buildings_direct": 2,
            "roads_direct_km": 1.5,
            "buildings_area_m2": 120,
        }
    }
    datasets = dict(_chart_datasets(state))
    assert "Număr elemente OSM" in datasets
    assert "Lungimi infrastructură liniară (km)" in datasets
    assert "Suprafețe clădiri (m²)" in datasets
    assert "Drumuri direct" not in datasets["Număr elemente OSM"]


def test_osm_dynamic_world_summary_handles_missing_data() -> None:
    text = _osm_dynamic_world_summary(_state())
    assert "0 km" in text
    assert "verificare" in text


def test_report_filename_and_mandatory_note() -> None:
    assert report_filename(_state()) == "raport_geoint_inundatie_galati_2024-09-14.pdf"
    assert "nu constituie confirmare oficială" in MANDATORY_NOTE


def test_report_filename_prefers_event_date() -> None:
    state = _state()
    state.event_date = "2024-09-20"
    assert report_filename(state).endswith("_2024-09-20.pdf")


def test_report_is_saved_to_requested_output_directory(tmp_path) -> None:
    state = _state()
    report_path = save_report_pdf(state, b"%PDF-test", tmp_path)

    assert report_path == tmp_path / report_filename(state)
    assert report_path.read_bytes() == b"%PDF-test"


def test_saved_pdf_validation_checks_file_existence(tmp_path) -> None:
    pdf = generate_report_pdf(_state())
    report_path = save_report_pdf(_state(), pdf, tmp_path)

    validation = validate_report_pdf(pdf, report_path)

    assert validation["exists"]
    assert validation["size_bytes"] == len(pdf)
    assert validation["error"] is None


def test_pdf_rapid_detailed_and_missing_data() -> None:
    rapid = _state()
    rapid.analysis_mode = "rapid"
    detailed = _state()
    detailed.analysis_mode = "detaliat"
    detailed.analysis_results["dynamic_world"] = {
        "status": "indisponibil",
        "error": "fără observații",
        "metrics": {},
    }
    assert generate_report_pdf(rapid).startswith(b"%PDF")
    assert generate_report_pdf(detailed).startswith(b"%PDF")


def test_dynamic_world_tile_errors_are_human_readable_in_report() -> None:
    state = _state()
    state.analysis_results["dynamic_world"] = {
        "tiles": {
            "dynamic_world_before": {
                "status": "tile indisponibil",
                "error": "URL indisponibil",
            },
            "dynamic_world_after": {
                "status": "reușit",
                "url": "https://tiles/after",
            },
        }
    }
    summary = _dynamic_world_tile_summary(state)
    assert "BEFORE: tile indisponibil (URL indisponibil)" in summary
    assert "AFTER: reușit" in summary
    assert "{" not in summary

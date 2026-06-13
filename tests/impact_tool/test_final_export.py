from __future__ import annotations

import csv
import json

from src.impact_tool.final_export import (
    NOT_VALIDATED,
    export_final_run_package,
    final_run_payload,
)
from src.impact_tool.models import ImpactToolState


def test_export_marks_missing_results_without_inventing_values(tmp_path) -> None:
    state = ImpactToolState()

    payload = final_run_payload(state)
    paths = export_final_run_package(state, tmp_path)

    assert payload["final_run_status"] == NOT_VALIDATED
    assert payload["scenes"]["before"] == NOT_VALIDATED
    assert payload["sar"]["metrics"] == NOT_VALIDATED
    assert payload["dynamic_world"]["metrics"] == NOT_VALIDATED
    assert payload["osm"]["metrics"] == NOT_VALIDATED
    assert paths["json"].is_file()
    assert paths["csv"].is_file()
    assert paths["markdown"].is_file()


def test_export_json_and_csv_are_readable(tmp_path) -> None:
    state = ImpactToolState(
        analysis_complete=True,
        before_scene={
            "ee_id": "before",
            "acquisition_time": "2024-09-01T00:00:00Z",
        },
        after_scene={
            "ee_id": "after",
            "acquisition_time": "2024-09-14T00:00:00Z",
        },
        analysis_results={
            "sar_status": {"metrics_available": True},
            "sar": {
                "metrics": {
                    "sar_new_water_area_km2": {
                        "status": "reușit",
                        "value": 1.25,
                        "error": None,
                    }
                }
            },
        },
    )

    paths = export_final_run_package(state, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    with paths["csv"].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    assert payload["final_run_status"] == "validat_tehnic_local"
    assert payload["sar"]["metrics"]["sar_new_water_area_km2"]["value"] == 1.25
    assert rows[0] == ["field", "value"]
    assert any(row[0] == "final_run_status" for row in rows)


def test_final_status_is_separate_from_smoke_test() -> None:
    payload = final_run_payload(ImpactToolState())

    assert payload["final_run_status"] == NOT_VALIDATED
    assert "LOCAL_RUN_REPORT.md" in payload["smoke_test_status"]
    assert payload["repository"]
    assert payload["branch"]
    assert payload["limitations"]


def test_export_omits_large_vector_geometries() -> None:
    state = ImpactToolState(
        analysis_results={
            "sar": {
                "vectorization": {
                    "status": "reușit",
                    "geometry": {"type": "Polygon", "coordinates": []},
                    "display_geometry": {
                        "type": "Polygon",
                        "coordinates": [],
                    },
                    "scale_meters": 30,
                }
            }
        }
    )

    vectorization = final_run_payload(state)["sar"]["vectorization"]

    assert vectorization == {"status": "reușit", "scale_meters": 30}

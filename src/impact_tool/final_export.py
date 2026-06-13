from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.impact_tool.models import ImpactToolState
from src.impact_tool.report import DEFAULT_REPORTS_DIR


NOT_VALIDATED = "[NEVALIDAT TEHNIC]"
DEFAULT_FINAL_RUN_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "output" / "final_run"
)


def export_final_run_package(
    state: ImpactToolState,
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    destination = Path(output_dir) if output_dir else DEFAULT_FINAL_RUN_DIR
    destination.mkdir(parents=True, exist_ok=True)
    payload = final_run_payload(state)
    json_path = destination / "results_summary.json"
    csv_path = destination / "results_summary.csv"
    markdown_path = destination / "FINAL_GALATI_VALIDATION.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["field", "value"])
        writer.writerows(_flatten_payload(payload))
    markdown_path.write_text(_validation_markdown(payload), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}


def final_run_payload(state: ImpactToolState) -> dict[str, Any]:
    sar = state.analysis_results.get("sar") or {}
    dynamic = state.analysis_results.get("dynamic_world") or {}
    osm = state.analysis_results.get("osm_impact") or {}
    errors = {
        key: value
        for key, value in state.analysis_results.items()
        if key.endswith("_error") and value
    }
    if state.analysis_error:
        errors["analysis_error"] = state.analysis_error
    pdf_path = (
        str(DEFAULT_REPORTS_DIR / state.report_filename)
        if state.report_filename
        else NOT_VALIDATED
    )
    sar_status = state.analysis_results.get("sar_status") or {}
    final_status = (
        "validat_tehnic_local"
        if state.analysis_complete
        and state.before_scene
        and state.after_scene
        and sar_status.get("metrics_available")
        else NOT_VALIDATED
    )
    return {
        "repository": _git_repository(),
        "branch": _git_branch(),
        "commit": _git_commit(),
        "run_date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "final_run_status": final_status,
        "smoke_test_status": "separat; vezi LOCAL_RUN_REPORT.md",
        "county": state.county_name,
        "event_date": state.event_date or NOT_VALIDATED,
        "scenes": {
            "before": _scene_export(state.before_scene),
            "after": _scene_export(state.after_scene),
            "compatibility": state.scene_pair_validation or NOT_VALIDATED,
            "overrides": {
                "relative_orbit_experimental": state.relative_orbit_override,
                "low_coverage": state.low_coverage_override,
            },
        },
        "area": {
            "type": "AOI" if state.aoi_active else "county",
            "bbox": state.active_area_bbox or NOT_VALIDATED,
            "area_km2": (
                state.active_area_km2
                if state.active_area_km2 > 0
                else NOT_VALIDATED
            ),
            "geometry_hash": state.active_area_hash or NOT_VALIDATED,
        },
        "parameters": {
            **state.analysis_parameters,
            "threshold_mode": state.sar_threshold_mode,
            "analysis_mode": state.analysis_mode,
            "buffer_meters": state.buffer_meters,
        },
        "sar": {
            "status": sar_status or NOT_VALIDATED,
            "metrics": sar.get("metrics") or NOT_VALIDATED,
            "vectorization": _vectorization_export(
                sar.get("vectorization")
            ),
            "qa": state.analysis_results.get("sar_qa") or NOT_VALIDATED,
        },
        "dynamic_world": {
            "status": dynamic.get("status") or NOT_VALIDATED,
            "metrics": (
                dynamic.get("metric_values")
                or dynamic.get("metrics")
                or NOT_VALIDATED
            ),
            "dates": dynamic.get("acquisition_dates") or NOT_VALIDATED,
        },
        "osm": {
            "status": (
                state.analysis_results.get("osm_load_status")
                or NOT_VALIDATED
            ),
            "metrics": osm.get("metrics") or NOT_VALIDATED,
            "sources": state.osm_status or NOT_VALIDATED,
        },
        "timings_seconds": state.timings or NOT_VALIDATED,
        "errors": errors or [],
        "limitations": [
            "Rezultatele reprezintă produse GEOINT preliminare de suport decizional.",
            "Intersecțiile OSM indică elemente potențial expuse, nu pagube confirmate.",
            "Diferențele observate Dynamic World necesită interpretare și verificare în teren.",
        ],
        "pdf_path": pdf_path,
    }


def _scene_export(scene: dict[str, Any] | None) -> dict[str, Any] | str:
    if not scene:
        return NOT_VALIDATED
    keys = (
        "ee_id",
        "display_id",
        "acquisition_time",
        "polarization",
        "instrument_mode",
        "orbit_pass",
        "relative_orbit",
        "coverage_percent",
    )
    return {key: scene.get(key, NOT_VALIDATED) for key in keys}


def _vectorization_export(
    vectorization: dict[str, Any] | None,
) -> dict[str, Any] | str:
    if not vectorization:
        return NOT_VALIDATED
    return {
        key: value
        for key, value in vectorization.items()
        if key not in {"geometry", "display_geometry"}
    }


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except Exception:
        return NOT_VALIDATED


def _git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "branch", "--show-current"],
            text=True,
            encoding="utf-8",
        ).strip() or NOT_VALIDATED
    except Exception:
        return NOT_VALIDATED


def _git_repository() -> str:
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True,
            encoding="utf-8",
        ).strip()
        if remote.startswith(("http://", "https://")):
            parsed = urlsplit(remote)
            hostname = parsed.hostname or ""
            if parsed.port:
                hostname = f"{hostname}:{parsed.port}"
            remote = urlunsplit(
                (parsed.scheme, hostname, parsed.path, "", "")
            )
        return remote.removesuffix(".git")
    except Exception:
        return NOT_VALIDATED


def _flatten_payload(value: Any, prefix: str = "") -> list[list[str]]:
    rows: list[list[str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_payload(item, field))
    elif isinstance(value, list):
        rows.append([prefix, json.dumps(value, ensure_ascii=False, default=str)])
    else:
        rows.append([prefix, str(value)])
    return rows


def _validation_markdown(payload: dict[str, Any]) -> str:
    result_sections = {
        "area": payload["area"],
        "parameters": payload["parameters"],
        "sar": payload["sar"],
        "dynamic_world": payload["dynamic_world"],
        "osm": payload["osm"],
        "timings_seconds": payload["timings_seconds"],
        "errors": payload["errors"],
    }
    return "\n".join(
        [
            "# Validare finală Galați",
            "",
            f"- Data rulării: {payload['run_date']}",
            f"- Commit: `{payload['commit']}`",
            f"- Status rulare finală: **{payload['final_run_status']}**",
            f"- Smoke test: {payload['smoke_test_status']}",
            f"- Județ: {payload['county']}",
            f"- PDF: `{payload['pdf_path']}`",
            "",
            "## Scene",
            "",
            "```json",
            json.dumps(payload["scenes"], indent=2, ensure_ascii=False),
            "```",
            "",
            "## Parametri și rezultate",
            "",
            "Valorile absente sunt marcate explicit și nu au fost inventate.",
            "",
            "```json",
            json.dumps(result_sections, indent=2, ensure_ascii=False),
            "```",
        ]
    )

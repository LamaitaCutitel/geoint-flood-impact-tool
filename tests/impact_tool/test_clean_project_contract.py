from __future__ import annotations

from pathlib import Path

from src.impact_tool.models import ImpactToolState
from src.impact_tool.state import update_buffer


ROOT = Path(__file__).resolve().parents[2]


def _active_python_source() -> str:
    paths = [
        ROOT / "impact_tool.py",
        *(ROOT / "src" / "impact_tool").rglob("*.py"),
        *(ROOT / "src" / "gee").rglob("*.py"),
        *(ROOT / "src" / "app_support").rglob("*.py"),
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()


def test_clean_tool_has_no_excluded_water_or_terrain_dependencies():
    source = _active_python_source()
    for excluded in (
        "global surface water",
        "srtm",
        "opentopography",
        "openrouteservice",
        "google drive",
    ):
        assert excluded not in source


def test_buffer_change_keeps_sar_and_invalidates_osm_and_report_only():
    sar = {"new_water_geometry": {"type": "Polygon", "coordinates": []}}
    state = ImpactToolState(
        analysis_complete=True,
        analysis_results={"sar": sar, "osm_impact": {"layers": {}}},
        report_bytes=b"pdf",
        report_filename="report.pdf",
        osm_impact_available=True,
    )
    assert update_buffer(state, 300)
    assert state.analysis_results["sar"] is sar
    assert "osm_impact" not in state.analysis_results
    assert state.osm_impact_available is False
    assert state.report_bytes is None

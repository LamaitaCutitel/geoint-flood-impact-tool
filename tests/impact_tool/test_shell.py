from __future__ import annotations

from pathlib import Path

from src.impact_tool.models import (
    BUFFER_DEFAULT_METERS,
    BUFFER_MAX_METERS,
    BUFFER_MIN_METERS,
    LAYER_GROUPS,
    TAB_NAMES,
    ImpactToolState,
    WIZARD_STEPS,
)
from src.impact_tool.workflow import workflow_steps
from src.impact_tool.ui.results import _osm_source_label


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _new_tool_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src/impact_tool").rglob("*.py")
    )


def test_shell_declares_required_tabs_and_layer_groups():
    assert TAB_NAMES == (
        "Hartă",
        "Rezumat impact",
        "Dynamic World",
        "Elemente OSM",
        "Raport",
    )
    assert LAYER_GROUPS == (
        "Analiză SAR",
        "Dynamic World",
        "Corelare multisursă",
        "Impact OSM",
    )


def test_wizard_contains_all_six_steps():
    state = ImpactToolState()
    steps = workflow_steps(state)

    assert len(steps) == 6
    assert tuple(step.label for step in steps) == WIZARD_STEPS
    assert steps[0].complete is True
    assert steps[2].active is True


def test_buffer_limits_and_default():
    state = ImpactToolState()

    assert BUFFER_MIN_METERS == 1
    assert BUFFER_MAX_METERS == 1000
    assert BUFFER_DEFAULT_METERS == 250
    assert state.buffer_meters == 250


def test_actions_are_disabled_before_analysis():
    state = ImpactToolState()

    assert state.can_run_analysis is False
    assert state.can_download_report is False
    assert state.swipe_enabled is False


def test_shell_contains_required_controls():
    source = _new_tool_source()

    assert "Buffer în jurul apei noi" in source
    assert "Desenează zonă focală" in source
    assert "Șterge AOI și revino la județ" in source
    assert "Rulează analiza SAR" in source
    assert "Încarcă obiective importante" in source
    assert "Analizează impactul OSM" in source
    assert "Rulează / Reîncearcă Dynamic World" in source
    assert "Generează și descarcă raportul PDF" in source
    assert "disabled=not state.can_run_analysis" in source
    assert "disabled=not state.can_download_report" in source


def test_osm_source_label_distinguishes_cache_from_live_download():
    assert _osm_source_label({"roads": {"ok": True, "source": "cache"}}) == "cache local"
    assert (
        _osm_source_label({"roads": {"ok": True, "source": "Overpass API"}})
        == "descarcare live Overpass API"
    )


def test_new_tool_excludes_disallowed_products_and_technical_layers():
    source = _new_tool_source().lower()
    disallowed = (
        "global surface water",
        "sentinel-2",
        "hillshade",
        "slope",
        "geopandas",
        "weasyprint",
        "selenium",
        "playwright",
    )

    assert all(term not in source for term in disallowed)


def test_shell_has_single_leaflet_draw_control_and_no_analysis_layers():
    source = _new_tool_source()

    assert source.count("Draw(") == 1
    assert "SAR ratio" not in source
    assert "SAR difference" not in source
    assert source.count("class SarSwipeControl") == 1
    assert "SideBySideLayers(" not in source
    assert "DynamicCompareControl" not in source


def test_layer_controls_are_processed_before_map_render():
    source = (PROJECT_ROOT / "src/impact_tool/ui/shell.py").read_text(encoding="utf-8")

    assert source.index("_render_layer_controls(st, state)") < source.index("st_folium(")

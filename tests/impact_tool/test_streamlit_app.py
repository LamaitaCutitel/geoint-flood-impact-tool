from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_streamlit_shell_renders_without_exception():
    app = AppTest.from_file(str(PROJECT_ROOT / "impact_tool.py"))
    app.run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "Evaluarea impactului unei inundații"
    assert [tab.label for tab in app.tabs] == [
        "Hartă",
        "Rezumat impact",
        "Dynamic World",
        "Elemente OSM",
        "Raport",
    ]
    rendered_markdown = "\n".join(item.value for item in app.markdown)
    assert "Selectează județul" in rendered_markdown
    assert "Generează raportul PDF" in rendered_markdown
    assert "Explorator temporal Sentinel-1" in rendered_markdown


def test_streamlit_controls_start_disabled():
    app = AppTest.from_file(str(PROJECT_ROOT / "impact_tool.py"))
    app.run(timeout=20)

    buttons = {button.label: button for button in app.button}
    assert buttons["Rulează analiza SAR"].disabled is True
    assert buttons["Generează și descarcă raportul PDF"].disabled is True

    buffer_slider = next(
        slider for slider in app.slider if slider.label == "Buffer în jurul apei noi"
    )
    assert buffer_slider.value == 250
    assert buffer_slider.min == 1
    assert buffer_slider.max == 1000

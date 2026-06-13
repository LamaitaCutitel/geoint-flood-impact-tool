from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_entrypoint_imports_without_running_streamlit():
    spec = importlib.util.spec_from_file_location(
        "impact_tool_entrypoint",
        PROJECT_ROOT / "impact_tool.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)


def test_expected_impact_tool_structure_exists():
    expected = [
        "impact_tool.py",
        "requirements.txt",
        "src/impact_tool/__init__.py",
        "src/impact_tool/models.py",
        "src/impact_tool/aoi.py",
        "src/impact_tool/state.py",
        "src/impact_tool/workflow.py",
        "src/impact_tool/ui/__init__.py",
        "src/impact_tool/ui/shell.py",
        "src/impact_tool/ui/sidebar.py",
        "src/impact_tool/ui/results.py",
        "src/impact_tool/map/__init__.py",
        "src/impact_tool/map/builder.py",
        "src/impact_tool/map/layers.py",
        "src/impact_tool/map/legend.py",
        "src/impact_tool/map/swipe.py",
    ]

    assert all((PROJECT_ROOT / path).exists() for path in expected)


def test_new_entrypoint_does_not_extend_experimental_dashboard():
    entrypoint = (PROJECT_ROOT / "impact_tool.py").read_text(encoding="utf-8")
    package_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src/impact_tool").rglob("*.py")
    )

    assert "import app" not in entrypoint
    assert "src.app.map_builder" not in package_source


def test_planned_dependencies_are_isolated():
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

    for dependency in (
        "streamlit",
        "folium",
        "streamlit-folium",
        "earthengine-api",
        "geemap",
        "pandas",
        "numpy",
        "plotly",
        "python-dotenv",
        "pytest",
        "shapely",
        "pyproj",
        "reportlab",
        "matplotlib",
        "requests",
    ):
        assert dependency in requirements

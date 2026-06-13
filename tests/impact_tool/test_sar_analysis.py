from __future__ import annotations

from src.impact_tool.sar import (
    SarParameters,
    _metric_statuses,
    _tile_status,
    _vector_geometry,
    recommended_sar_threshold,
    run_sar_analysis,
    sar_layer_definitions,
)
from src.impact_tool.models import ImpactToolState
from src.impact_tool.state import update_sar_parameters


class FakeImage:
    def __init__(self, expression: str):
        self.expression = expression

    def select(self, value):
        return FakeImage(f"select({self.expression},{value})")

    def clip(self, aoi):
        return FakeImage(f"clip({self.expression},{aoi})")

    def lt(self, value):
        return FakeImage(f"lt({self.expression},{value})")

    def selfMask(self):
        return FakeImage(f"mask({self.expression})")

    def connectedPixelCount(self, size, connected):
        return FakeImage(f"connected({self.expression})")

    def gte(self, value):
        return FakeImage(f"gte({self.expression},{value})")

    def updateMask(self, value):
        return FakeImage(f"update({self.expression})")

    def unmask(self, value):
        return FakeImage(f"unmask({self.expression})")

    def And(self, other):
        return FakeImage(f"and({self.expression},{other.expression})")

    def Not(self):
        return FakeImage(f"not({self.expression})")

    def getMapId(self, params):
        class Fetcher:
            url_format = "https://tiles/{z}/{x}/{y}"
        return {"tile_fetcher": Fetcher()}


class FakeEE:
    def Image(self, scene_id):
        return FakeImage(scene_id)


def _scene(scene_id, timestamp):
    return {
        "ee_id": scene_id,
        "polarization": "VH",
        "acquisition_time": timestamp,
    }


def test_strict_sar_analysis_builds_only_required_products(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.impact_tool.sar.sar_water_area_metrics",
        lambda ee, masks, aoi, scale: {f"{key}_area_km2": 1.0 for key in masks},
    )
    result = run_sar_analysis(
        FakeEE(),
        "county",
        _scene("before", "2024-01-01"),
        _scene("after", "2024-01-13"),
        SarParameters(minimum_connected_pixels=0),
    )
    assert set(result["metrics"]) == {
        "sar_water_before_area_km2",
        "sar_water_after_area_km2",
        "sar_new_water_area_km2",
    }
    assert result["products"]["sar_new_water"].expression.endswith(",county)")
    assert set(result["tiles"]) == {"sar_water_before", "sar_water_after", "sar_new_water"}
    assert all(item["status"] == "reușit" for item in result["metrics"].values())
    assert all(item["status"] == "reușit" for item in result["tiles"].values())


def test_sar_layers_have_no_technical_products() -> None:
    layers = sar_layer_definitions({"tiles": {}})
    names = {layer["name"] for layer in layers}
    assert names == {
        "Apă observată BEFORE",
        "Apă observată AFTER",
        "Apă nouă evidențiată prin SAR",
    }
    assert all("ratio" not in name.lower() and "difference" not in name.lower() for name in names)


def test_sar_parameter_change_invalidates_analysis_and_report() -> None:
    state = ImpactToolState(
        analysis_complete=True,
        analysis_results={"sar": {}, "dynamic_world": {}, "osm_impact": {}},
        report_bytes=b"pdf",
        report_filename="old.pdf",
        layer_compare_active=True,
    )

    changed = update_sar_parameters(state, water_threshold=-17.5)

    assert changed is True
    assert state.analysis_complete is False
    assert state.analysis_results == {}
    assert state.report_bytes is None
    assert state.layer_compare_active is False
    assert "Rulează din nou analiza" in state.sar_parameters_message


def test_metric_error_is_not_a_real_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.impact_tool.sar.sar_water_area_metrics",
        lambda *args: (_ for _ in ()).throw(RuntimeError("reduceRegion failed")),
    )

    metrics = _metric_statuses(object(), {"sar_new_water": object()}, object(), 10)

    assert metrics["sar_new_water_area_km2"]["status"] == "eroare"
    assert metrics["sar_new_water_area_km2"]["value"] is None
    assert "reduceRegion failed" in metrics["sar_new_water_area_km2"]["error"]


def test_vectorization_and_tile_failures_keep_diagnostics(monkeypatch) -> None:
    class BrokenMask:
        def reduceToVectors(self, **kwargs):
            raise RuntimeError("vector limit")

    monkeypatch.setattr(
        "src.impact_tool.sar.ee_tile_url",
        lambda *args: (_ for _ in ()).throw(RuntimeError("map id failed")),
    )

    vector = _vector_geometry(object(), BrokenMask(), object())
    tile = _tile_status(object(), "SAR")

    assert vector["status"] == "eroare"
    assert vector["geometry"] is None
    assert vector["error"] == "vector limit"
    assert vector["scale_meters"] == 10
    assert tile["status"] == "tile indisponibil"
    assert tile["url"] is None
    assert tile["error"] == "map id failed"


def test_vh_and_vv_threshold_recommendations_are_distinct() -> None:
    assert recommended_sar_threshold("VH", "echilibrat") == -18.0
    assert recommended_sar_threshold("VV", "echilibrat") == -15.0
    assert recommended_sar_threshold("VH", "conservator") == -20.0
    assert recommended_sar_threshold("VV", "sensibil") == -13.0


def test_sar_exports_analysis_and_vectorization_scales(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.impact_tool.sar.sar_water_area_metrics",
        lambda ee, masks, aoi, scale: {f"{key}_area_km2": 1.0 for key in masks},
    )
    result = run_sar_analysis(
        FakeEE(),
        "county",
        _scene("before", "2024-01-01"),
        _scene("after", "2024-01-13"),
        SarParameters(
            minimum_connected_pixels=0,
            analysis_scale_meters=10,
            vectorization_scale_meters=30,
        ),
    )

    assert result["parameters"]["analysis_scale_meters"] == 10
    assert result["parameters"]["vectorization_scale_meters"] == 30
    assert result["warnings"]


def test_vectorization_filters_small_polygons_and_exports_best_effort() -> None:
    calls = {}

    class Geometry:
        def area(self, **kwargs):
            return 1234

        def simplify(self, **kwargs):
            calls["simplify"] = kwargs
            return self

        def getInfo(self):
            return {"type": "Polygon", "coordinates": []}

    class Feature:
        def geometry(self):
            return Geometry()

        def set(self, key, value):
            calls["set"] = (key, value)
            return self

    class Collection:
        def map(self, callback):
            callback(Feature())
            return self

        def filter(self, filter_value):
            calls["filter"] = filter_value
            return self

        def geometry(self):
            return Geometry()

    class Mask:
        def reduceToVectors(self, **kwargs):
            calls["reduce"] = kwargs
            return Collection()

    class Filter:
        @staticmethod
        def gte(name, value):
            return name, value

    class EE:
        pass

    EE.Filter = Filter

    result = _vector_geometry(
        EE(),
        Mask(),
        "aoi",
        scale_meters=20,
        minimum_polygon_area_m2=1500,
        simplification_tolerance_m=25,
        best_effort=True,
    )

    assert calls["filter"] == ("area_m2", 1500)
    assert calls["reduce"]["scale"] == 20
    assert calls["reduce"]["bestEffort"] is True
    assert result["best_effort"] is True
    assert result["display_geometry"]["type"] == "Polygon"

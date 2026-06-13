from __future__ import annotations

from pathlib import Path

from src.impact_tool.dynamic_world import (
    TRANSITION_CLASSES,
    _combined_metric_statuses,
    _mandatory_tiles_ready,
    _metric_statuses,
    _needs_mosaic,
    _tile_status,
    correlate_osm_dynamic_world,
    dynamic_world_layer_definitions,
    scene_day_period,
)
from src.impact_tool.ui.results import _coverage_label


def test_coverage_below_85_percent_uses_mosaic() -> None:
    assert _needs_mosaic(0.8499)
    assert not _needs_mosaic(0.85)


def test_missing_coverage_is_not_rendered_as_false_zero() -> None:
    assert _coverage_label(None) == "indisponibilă"
    assert _coverage_label(0) == "0.0%"


def test_green_status_requires_all_mandatory_tiles() -> None:
    tiles = {
        key: {"status": "reușit", "url": f"https://tiles/{key}"}
        for key in (
            "dynamic_world_before",
            "dynamic_world_after",
            "dynamic_world_new_water",
        )
    }
    assert _mandatory_tiles_ready(tiles, tuple(tiles))
    tiles["dynamic_world_after"]["url"] = None
    assert not _mandatory_tiles_ready(tiles, tuple(tiles))


def test_combined_metrics_use_one_reduce_region() -> None:
    calls = []

    class Result:
        def getInfo(self):
            return {"metric_0": 1_000_000, "metric_1": 2_000_000}

    class Combined:
        def reduceRegion(self, **kwargs):
            calls.append(kwargs)
            return Result()

    class Mask:
        def multiply(self, other):
            return self

        def rename(self, name):
            return self

    class Image:
        @staticmethod
        def pixelArea():
            return object()

        @staticmethod
        def cat(*images):
            return Combined()

    class Reducer:
        @staticmethod
        def sum():
            return "sum"

    class Ee:
        pass

    Ee.Image = Image
    Ee.Reducer = Reducer
    result = _combined_metric_statuses(
        Ee,
        {"first": Mask(), "second": Mask()},
        object(),
        10,
    )
    assert len(calls) == 1
    assert result["first"]["value"] == 1.0
    assert result["second"]["value"] == 2.0


def test_scene_period_uses_robust_window_around_acquisition() -> None:
    period = scene_day_period({"acquisition_time": "2024-09-14T16:27:00+00:00"})
    assert period == ("2024-08-30", "2024-09-30")


def test_all_relevant_transitions_are_declared() -> None:
    assert set(TRANSITION_CLASSES.values()) == {
        "crops",
        "grass",
        "built",
        "trees",
        "flooded vegetation",
        "shrub and scrub",
        "bare",
    }


def test_dynamic_world_and_correlation_layers() -> None:
    layers = dynamic_world_layer_definitions({"tiles": {}})
    names = {layer["name"] for layer in layers}
    assert "Dynamic World BEFORE" in names
    assert "Dynamic World AFTER" in names
    assert "Apă nouă prin ambele metode" in names
    assert "Apă nouă doar SAR" in names
    assert "Apă nouă doar Dynamic World" in names
    new_water = next(
        layer for layer in layers if layer["id"] == "dynamic_world_new_water"
    )
    assert new_water["shown"] is True


def test_structured_tile_error_is_visible(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.impact_tool.dynamic_world.ee_tile_url",
        lambda *args: None,
    )
    status = _tile_status(object(), "Dynamic World before")
    assert status["url"] is None
    assert status["status"] == "tile indisponibil"
    assert status["error"]
    layer = dynamic_world_layer_definitions(
        {"tiles": {"dynamic_world_before": status}}
    )[0]
    assert layer["tile_status"] == "tile indisponibil"
    assert layer["tile_error"]


def test_real_zero_is_distinct_from_metric_error(monkeypatch) -> None:
    def strict_area(ee, mask, aoi, scale):
        if mask == "broken":
            raise RuntimeError("reduceRegion failed")
        return 0.0

    monkeypatch.setattr(
        "src.impact_tool.dynamic_world._strict_mask_area_km2",
        strict_area,
    )
    result = _metric_statuses(
        object(),
        {"real_zero": "zero", "failed": "broken"},
        object(),
        10,
    )
    assert result["real_zero"] == {
        "value": 0.0,
        "status": "reușit",
        "error": None,
    }
    assert result["failed"]["value"] is None
    assert result["failed"]["status"] == "eroare"
    assert "reduceRegion failed" in result["failed"]["error"]


def test_fallback_mosaic_and_effective_date_are_declared() -> None:
    source = Path("src/impact_tool/dynamic_world.py").read_text(encoding="utf-8")
    assert "dynamic_world_mode" in source
    assert '"mozaic fallback"' in source
    assert '"acquisition_dates"' in source
    assert '"product_types"' in source


def test_osm_dynamic_world_correlation_uses_before_after_classes() -> None:
    class SampleResult:
        def __init__(self, features, label):
            self.features = features
            self.label = label

        def getInfo(self):
            return {
                "features": [
                    {
                        "properties": {
                            "feature_key": feature["properties"]["feature_key"],
                            "label": self.label,
                        }
                    }
                    for feature in self.features
                ]
            }

    class FakeImage:
        def __init__(self, label):
            self.label = label

        def reduceRegions(self, collection, **kwargs):
            return SampleResult(collection, self.label)

    class FakeEe:
        @staticmethod
        def Feature(geometry, properties):
            return {"geometry": geometry, "properties": properties}

        @staticmethod
        def FeatureCollection(features):
            return features

    class Reducer:
        @staticmethod
        def mode():
            return "mode"

    FakeEe.Geometry = staticmethod(lambda geometry: geometry)
    FakeEe.Reducer = Reducer

    result = correlate_osm_dynamic_world(
        FakeEe(),
        {"products": {"before": FakeImage(4), "after": FakeImage(0)}},
        {
            "layers": {
                "osm_buildings": {
                    "features": [
                        {
                            "geometry": {
                                "type": "Point",
                                "coordinates": [27.5, 45.5],
                            },
                            "properties": {
                                "name": "Clădire test",
                                "status": "Intersectat direct",
                            },
                        }
                    ]
                }
            }
        },
    )
    assert result["status"] == "reușit"
    assert result["rows"][0]["before_class"] == "culturi"
    assert result["rows"][0]["after_class"] == "apă"
    assert result["rows"][0]["transition"] == "culturi → apă"


def test_dynamic_world_ui_exposes_both_correlations() -> None:
    source = Path("src/impact_tool/ui/results.py").read_text(encoding="utf-8")
    assert "Suprapunere SAR × Dynamic World" in source
    assert "Corelare OSM × Dynamic World" in source
    assert "dataframe" in source

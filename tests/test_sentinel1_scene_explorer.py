from datetime import date

from src.gee import sentinel1_scene_explorer
from src.gee.sentinel1_scene_explorer import (
    scene_recommendation_labels,
    search_sentinel1_scenes_result,
    validate_scene_pair,
)


def _scene(**overrides):
    scene = {
        "ee_id": "COPERNICUS/S1_GRD/S1A_TEST",
        "display_id": "S1A_TEST",
        "acquisition_time": "2024-09-01T16:27:00+00:00",
        "platform": "A",
        "polarization": "VH",
        "orbit_pass": "ASCENDING",
        "relative_orbit": 80,
        "instrument_mode": "IW",
        "resolution_meters": 10,
        "coverage_percent": 100,
        "warnings": [],
    }
    scene.update(overrides)
    return scene


def test_validate_scene_pair_accepts_matching_scenes():
    before = _scene(acquisition_time="2024-09-01T16:27:00+00:00")
    after = _scene(acquisition_time="2024-09-14T16:27:00+00:00")

    status = validate_scene_pair(before, after)

    assert status["compatible"] is True
    assert status["requires_confirmation"] is False


def test_validate_scene_pair_blocks_reversed_dates():
    before = _scene(acquisition_time="2024-09-20T16:27:00+00:00")
    after = _scene(acquisition_time="2024-09-14T16:27:00+00:00")

    status = validate_scene_pair(before, after)

    assert status["compatible"] is False
    assert "BEFORE trebuie sa fie anterioara" in status["errors"][0]


def test_validate_scene_pair_warns_on_relative_orbit_only():
    before = _scene(acquisition_time="2024-09-01T16:27:00+00:00", relative_orbit=80)
    after = _scene(acquisition_time="2024-09-14T16:27:00+00:00", relative_orbit=81)

    status = validate_scene_pair(before, after)

    assert status["compatible"] is True
    assert status["requires_confirmation"] is True


def test_validate_scene_pair_warns_on_low_coverage_without_blocking():
    before = _scene(acquisition_time="2024-09-01T16:27:00+00:00", coverage_percent=85)
    after = _scene(acquisition_time="2024-09-14T16:27:00+00:00", coverage_percent=91)

    status = validate_scene_pair(before, after)

    assert status["compatible"] is True
    assert any("acoperire AOI" in warning for warning in status["warnings"])


def test_recommendations_use_event_date():
    scenes = [
        _scene(ee_id="before_far", display_id="before_far", acquisition_time="2024-08-21T16:27:00+00:00"),
        _scene(ee_id="before_near", display_id="before_near", acquisition_time="2024-09-13T16:27:00+00:00"),
        _scene(ee_id="after_near", display_id="after_near", acquisition_time="2024-09-15T16:27:00+00:00"),
    ]

    labels_before = scene_recommendation_labels(scenes[1], scenes, None, None, date(2024, 9, 14))
    labels_after = scene_recommendation_labels(scenes[2], scenes, None, None, date(2024, 9, 14))

    assert "Recomandat BEFORE" in labels_before
    assert "Recomandat AFTER" in labels_after


def test_recommendations_prioritize_closest_valid_scene_to_event_date():
    scenes = [
        _scene(ee_id="before_compatible_far", display_id="before_compatible_far", acquisition_time="2024-08-20T16:27:00+00:00"),
        _scene(
            ee_id="before_near",
            display_id="before_near",
            acquisition_time="2024-09-13T16:27:00+00:00",
            relative_orbit=81,
        ),
        _scene(ee_id="after_near", display_id="after_near", acquisition_time="2024-09-15T16:27:00+00:00"),
    ]

    labels = scene_recommendation_labels(scenes[1], scenes, None, scenes[2], date(2024, 9, 14))

    assert "Recomandat BEFORE" in labels


class _FakeAoi:
    def area(self, scale):
        return 1


class _FakeCollection:
    def __init__(self, features=None, exc=None):
        self.features = features or []
        self.exc = exc

    def map(self, fn):
        return self

    def sort(self, field):
        return self

    def toList(self, limit):
        return self

    def getInfo(self):
        if self.exc:
            raise self.exc
        return self.features


def test_search_sentinel1_scenes_result_distinguishes_zero_results(monkeypatch):
    monkeypatch.setattr(
        sentinel1_scene_explorer,
        "get_sentinel1_collection",
        lambda *args, **kwargs: _FakeCollection([]),
    )

    result = search_sentinel1_scenes_result(object(), _FakeAoi(), "2024-09-01", "2024-09-02", "VH", "BOTH")

    assert result["scenes"] == []
    assert result["errors"] == []
    assert result["warnings"]
    assert result["query_parameters"]["polarization"] == "VH"


def test_search_sentinel1_scenes_result_classifies_auth_errors(monkeypatch):
    monkeypatch.setattr(
        sentinel1_scene_explorer,
        "get_sentinel1_collection",
        lambda *args, **kwargs: _FakeCollection(exc=Exception("Please authorize access")),
    )

    result = search_sentinel1_scenes_result(object(), _FakeAoi(), "2024-09-01", "2024-09-02", "VH", "BOTH")

    assert result["scenes"] == []
    assert result["errors"][0]["code"] == "gee_auth_missing"
    assert result["query_duration"] >= 0

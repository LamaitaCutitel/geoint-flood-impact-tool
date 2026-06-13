from __future__ import annotations

import requests

from src.impact_tool.external.geoapify_places import (
    fetch_important_facilities,
    fetch_places,
    normalize_category,
    normalize_places,
)
from src.impact_tool.external.http import build_session, configured_timeout
from src.impact_tool.external.maptiler import county_buildings_context
from src.impact_tool.external.overpass_targeted import run_targeted_query


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


def test_http_session_has_user_agent_and_bounded_timeout(monkeypatch):
    monkeypatch.setenv("EXTERNAL_API_TIMEOUT_SECONDS", "120")
    session = build_session()
    assert "geoint-flood-impact-tool" in session.headers["User-Agent"]
    assert configured_timeout() == (5.0, 60.0)


def test_maptiler_missing_key_degrades_without_exposing_secret():
    result = county_buildings_context("")
    assert not result.status.ok
    assert result.data is None
    assert "lipsește" in result.status.warning


def test_maptiler_context_uses_raster_tiles_only():
    result = county_buildings_context("test-key")
    assert result.status.ok
    assert ".png" in result.data["tile_url"]
    assert ".pbf" not in result.data["tile_url"]


def test_geoapify_places_is_normalized_and_mocked():
    session = FakeSession([{"type": "FeatureCollection", "features": []}])
    result = fetch_places(
        categories=["healthcare.hospital"],
        filter_value="rect:1,2,3,4",
        api_key="secret-value",
        session=session,
    )
    assert result.status.ok
    assert result.status.source == "Geoapify Places"
    assert result.data["features"] == []
    assert "secret-value" not in result.status.warning


def test_geoapify_categories_and_duplicate_ids_are_normalized():
    payload = {
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "place_id": "same",
                    "name": "Spital",
                    "formatted": "Strada Test 1",
                    "categories": ["healthcare.hospital"],
                },
                "geometry": {"type": "Point", "coordinates": [28.0, 45.5]},
            },
            {
                "type": "Feature",
                "properties": {"place_id": "same", "categories": ["service.police"]},
                "geometry": {"type": "Point", "coordinates": [28.1, 45.6]},
            },
        ]
    }
    result = normalize_places(payload)
    assert len(result["features"]) == 1
    properties = result["features"][0]["properties"]
    assert properties["category"] == "hospital"
    assert properties["address"] == "Strada Test 1"
    assert properties["source_id"] == "same"
    assert normalize_category(["unknown.category"]) == "fallback"


def test_missing_geoapify_key_can_use_reduced_fallback():
    fallback_result = run_targeted_query(
        "query",
        session=FakeSession([{"elements": []}]),
        endpoints=["https://fallback.test"],
    )
    result = fetch_important_facilities(
        filter_value="rect:1,2,3,4",
        api_key="",
        fallback=lambda: fallback_result,
    )
    assert result.status.ok
    assert result.status.completeness == "posibil incomplet"
    assert "fallback" in result.status.warning


def test_overpass_uses_fallback_and_marks_partial_result():
    session = FakeSession(
        [requests.Timeout("timeout"), {"elements": [{"type": "node", "id": 1}]}]
    )
    result = run_targeted_query(
        "[out:json];node(1,2,3,4);out;",
        session=session,
        endpoints=["https://first.test", "https://second.test"],
    )
    assert result.status.ok
    assert result.status.completeness == "posibil incomplet"
    assert len(session.calls) == 2


def test_overpass_failure_keeps_empty_partial_data():
    session = FakeSession([requests.Timeout("timeout")])
    result = run_targeted_query(
        "[out:json];node(1,2,3,4);out;",
        session=session,
        endpoints=["https://only.test"],
    )
    assert not result.status.ok
    assert result.data == {"elements": []}

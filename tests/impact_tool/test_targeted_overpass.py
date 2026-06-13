from __future__ import annotations

import requests

from src.impact_tool.external.models import ExternalResult
from src.impact_tool.external.overpass_targeted import (
    build_targeted_query,
    deduplicate_elements,
    fetch_targeted_impact,
    targeted_bboxes,
    targeted_query_plan,
)


WATER = {
    "type": "Polygon",
    "coordinates": [
        [[27.5, 45.4], [27.55, 45.4], [27.55, 45.45], [27.5, 45.45], [27.5, 45.4]]
    ],
}


def test_targeted_geometry_is_required_and_bbox_is_reduced():
    try:
        targeted_bboxes({}, 250)
    except ValueError as error:
        assert "obligatorie" in str(error)
    boxes = targeted_bboxes(WATER, 250)
    assert 1 <= len(boxes) <= 4
    assert all(box[0] > 27 and box[2] < 28 for box in boxes)


def test_category_query_uses_only_reduced_bbox():
    query = build_targeted_query("buildings", [27.4, 45.3, 27.6, 45.5], 100)
    assert '["building"]' in query
    assert "45.3,27.4,45.5,27.6" in query
    assert "area[" not in query


def test_component_aware_plan_records_query_metadata():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            WATER["coordinates"],
            [[[27.7, 45.7], [27.72, 45.7], [27.72, 45.72], [27.7, 45.72], [27.7, 45.7]]],
        ],
    }
    plan = targeted_query_plan(geometry, 250, max_tiles=4)
    assert plan["component_count"] == 2
    assert 1 <= plan["query_box_count"] <= 4
    assert plan["covered_area_km2"] > 0
    assert plan["discarded_small_components"] >= 0


def test_targeted_roads_use_operational_classes():
    query = build_targeted_query("roads", [27.4, 45.3, 27.6, 45.5], 100)
    assert "motorway" in query
    assert "residential" in query
    assert "service" in query
    assert 'way["highway"](' not in query


def test_dedup_uses_stable_type_and_id():
    unique, duplicates = deduplicate_elements(
        [
            {"type": "way", "id": 1},
            {"type": "way", "id": 1},
            {"type": "node", "id": 1},
        ]
    )
    assert len(unique) == 2
    assert duplicates == 1


def test_partial_timeout_keeps_loaded_categories():
    calls = []

    def fetcher(query):
        calls.append(query)
        if '["building"]' in query:
            return ExternalResult.failure(source="Overpass", warning="timeout")
        return ExternalResult.success(
            {"elements": [{"type": "way", "id": len(calls)}]},
            source="Overpass",
            duration_seconds=0,
        )

    result = fetch_targeted_impact(
        water_geometry=WATER,
        buffer_meters=250,
        categories=("buildings", "roads"),
        fetcher=fetcher,
    )
    assert result.status.ok
    assert result.status.completeness == "posibil incomplet"
    assert result.data["categories"]["roads"]
    assert result.data["categories"]["buildings"] == []
    assert result.data["metadata"]["category_status"]["buildings"]["ok"] is False
    assert result.data["metadata"]["category_status"]["roads"]["ok"] is True


def test_hard_cap_truncates_without_crashing():
    def fetcher(_query):
        return ExternalResult.success(
            {"elements": [{"type": "way", "id": index} for index in range(10)]},
            source="Overpass",
            duration_seconds=0,
        )

    result = fetch_targeted_impact(
        water_geometry=WATER,
        buffer_meters=250,
        categories=("roads",),
        fetcher=fetcher,
        hard_cap=3,
    )
    assert len(result.data["categories"]["roads"]) == 3
    assert result.data["metadata"]["truncated"] is True
    assert "trunchiată" in result.status.warning

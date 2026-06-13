from src.app_support.osm_impact import (
    build_osm_geojson_layers,
    build_overpass_query,
    expanded_bbox,
    fetch_osm_operational_impact,
    fetch_osm_operational_impact_payload,
    filter_osm_layers_to_geometry,
    _fetch_overpass_by_category,
    summarize_osm_elements,
)


def test_expanded_bbox_adds_buffer():
    bbox = [27.0, 45.0, 28.0, 46.0]
    expanded = expanded_bbox(bbox, 1000)

    assert expanded[0] < bbox[0]
    assert expanded[1] < bbox[1]
    assert expanded[2] > bbox[2]
    assert expanded[3] > bbox[3]


def test_summarize_osm_elements_counts_operational_assets():
    elements = [
        {"type": "node", "id": 1, "lat": 45.0, "lon": 27.0},
        {"type": "node", "id": 2, "lat": 45.0, "lon": 27.01},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"building": "yes"}},
        {"type": "way", "id": 11, "nodes": [1, 2], "tags": {"highway": "primary"}},
        {"type": "way", "id": 12, "nodes": [1, 2], "tags": {"railway": "rail"}},
        {"type": "node", "id": 3, "lat": 45.0, "lon": 27.02, "tags": {"amenity": "hospital"}},
        {"type": "way", "id": 13, "nodes": [1, 2], "tags": {"bridge": "yes"}},
    ]

    metrics = summarize_osm_elements(elements, 500, 5000)

    assert metrics["osm_buildings_potentially_affected"] == 1
    assert metrics["osm_roads_intersected_km"] > 0
    assert metrics["osm_railways_intersected_km"] > 0
    assert metrics["osm_critical_assets"] == 1
    assert metrics["osm_bridges"] == 1


def test_fetch_osm_operational_impact_uses_injected_fetcher():
    def fetcher(query):
        assert "building" in query
        return {"elements": []}

    metrics = fetch_osm_operational_impact([27.0, 45.0, 28.0, 46.0], fetcher=fetcher)

    assert metrics["osm_elements_returned"] == 0
    assert metrics["osm_query_buffer_m"] == 500
    assert metrics["osm_query_errors"] == []


def test_osm_payload_contains_geojson_layers():
    def fetcher(query):
        return {
            "elements": [
                {"type": "node", "id": 1, "lat": 45.0, "lon": 27.0},
                {"type": "node", "id": 2, "lat": 45.0, "lon": 27.01},
                {"type": "way", "id": 10, "nodes": [1, 2, 1], "tags": {"highway": "primary", "bridge": "yes"}},
            ]
        }

    payload = fetch_osm_operational_impact_payload([27.0, 45.0, 28.0, 46.0], fetcher=fetcher)

    assert payload["metrics"]["osm_bridges"] == 1
    assert payload["layers"]["osm_roads"]["features"]
    assert payload["layers"]["osm_bridges"]["features"]


def test_osm_payload_filters_layers_to_county_geometry():
    county_geometry = {
        "type": "Polygon",
        "coordinates": [[
            [27.0, 45.0],
            [27.2, 45.0],
            [27.2, 45.2],
            [27.0, 45.2],
            [27.0, 45.0],
        ]],
    }

    def fetcher(query):
        return {
            "elements": [
                {"type": "node", "id": 1, "lat": 45.1, "lon": 27.1, "tags": {"amenity": "hospital", "name": "in judet"}},
                {"type": "node", "id": 2, "lat": 45.5, "lon": 27.5, "tags": {"amenity": "hospital", "name": "in afara"}},
            ]
        }

    payload = fetch_osm_operational_impact_payload(
        [27.0, 45.0, 28.0, 46.0],
        fetcher=fetcher,
        county_geometry=county_geometry,
    )

    critical = payload["layers"]["osm_critical"]["features"]
    assert len(critical) == 1
    assert critical[0]["properties"]["name"] == "in judet"
    assert payload["metrics"]["osm_critical_assets"] == 1


def test_filter_osm_layers_to_geometry_removes_outside_features():
    county_geometry = {
        "type": "Polygon",
        "coordinates": [[
            [27.0, 45.0],
            [27.2, 45.0],
            [27.2, 45.2],
            [27.0, 45.2],
            [27.0, 45.0],
        ]],
    }
    layers = {
        "osm_buildings": {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [27.1, 45.1]}, "properties": {}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [27.8, 45.8]}, "properties": {}},
            ],
        }
    }

    filtered = filter_osm_layers_to_geometry(layers, county_geometry)

    assert len(filtered["osm_buildings"]["features"]) == 1


def test_build_osm_geojson_layers_groups_operational_features():
    layers = build_osm_geojson_layers(
        [
            {"type": "node", "id": 1, "lat": 45.0, "lon": 27.0},
            {"type": "node", "id": 2, "lat": 45.0, "lon": 27.01},
            {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"railway": "rail"}},
            {"type": "node", "id": 3, "lat": 45.0, "lon": 27.02, "tags": {"amenity": "hospital"}},
        ]
    )

    assert layers["osm_railways"]["features"][0]["properties"]["exposure_label"] == "cale ferata intersectata"
    assert layers["osm_critical"]["features"][0]["properties"]["exposure_level"] == "high"
    assert layers["osm_critical"]["features"][0]["properties"]["osm_id"] == 3


def test_category_query_limits_requested_osm_payload():
    buildings_query = build_overpass_query([27.0, 45.0, 28.0, 46.0], 100, category="buildings")
    critical_query = build_overpass_query([27.0, 45.0, 28.0, 46.0], 100, category="critical")

    assert 'way["building"]' in buildings_query
    assert "highway" not in buildings_query
    assert "amenity" in critical_query
    assert "hospital" in critical_query


def test_fetch_overpass_by_category_keeps_partial_results(monkeypatch):
    from src.app_support import osm_impact

    def fake_cached(query):
        if "building" in query:
            raise TimeoutError("timeout")
        return {"elements": [{"type": "node", "id": 1, "lat": 45.0, "lon": 27.0}]}

    monkeypatch.setattr(osm_impact, "_cached_overpass", fake_cached)

    elements, errors = _fetch_overpass_by_category([27.0, 45.0, 28.0, 46.0], 5000)

    assert elements
    assert errors and "buildings" in errors[0]

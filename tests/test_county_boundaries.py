from src.app_support.county_boundaries import (
    bbox_center,
    county_display_name,
    county_names,
    feature_bbox,
    normalize_county_name,
    selected_county_feature,
    zoom_for_bbox,
)


def _geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"NAME_LATN": "Galaţi", "CNTR_CODE": "RO"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[27.0, 45.0], [28.0, 45.0], [28.0, 46.0], [27.0, 46.0], [27.0, 45.0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"NAME_LATN": "Alba", "CNTR_CODE": "RO"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[23.0, 45.5], [24.0, 45.5], [24.0, 46.5], [23.0, 46.5], [23.0, 45.5]]],
                },
            },
        ],
    }


def test_county_names_are_normalized_and_sorted():
    assert county_names(_geojson()) == ["Alba", "Galati"]


def test_normalize_county_name_handles_gisco_encoding():
    assert normalize_county_name("GalaÅ£i") == "Galati"
    assert normalize_county_name("Alba") == "Alba"


def test_selected_county_and_bbox_helpers():
    feature = selected_county_feature(_geojson(), "Galati")
    assert feature is not None
    assert county_display_name(feature) == "Galati"
    assert feature_bbox(feature) == [27.0, 45.0, 28.0, 46.0]
    assert bbox_center([27.0, 45.0, 28.0, 46.0]) == [45.5, 27.5]
    assert zoom_for_bbox([27.0, 45.0, 28.0, 46.0]) == 10

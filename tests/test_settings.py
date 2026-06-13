from datetime import date

from config.settings import (
    GALATI_PRESET,
    GEE_DYNAMIC_WORLD_COLLECTION,
    GEE_S1_COLLECTION,
    GEE_SENTINEL2_COLLECTION,
    PROFILE_SCALES,
    validate_analysis_parameters,
)


def test_required_gee_collections_are_exact():
    assert GEE_S1_COLLECTION == "COPERNICUS/S1_GRD"
    assert GEE_DYNAMIC_WORLD_COLLECTION == "GOOGLE/DYNAMICWORLD/V1"
    assert GEE_SENTINEL2_COLLECTION == "COPERNICUS/S2_SR_HARMONIZED"


def test_galati_preset_dates():
    assert GALATI_PRESET["before_start_date"] == date(2024, 8, 20)
    assert GALATI_PRESET["after_start_date"] == date(2024, 9, 14)
    assert GALATI_PRESET["event_date"] == date(2024, 9, 14)


def test_profile_scales():
    assert PROFILE_SCALES["Rapid preview"] == 40
    assert PROFILE_SCALES["Standard"] == 20
    assert PROFILE_SCALES["Detailed export"] == 10


def test_validate_analysis_parameters_accepts_defaults():
    warnings = validate_analysis_parameters(
        {
            "before_start_date": date(2024, 8, 20),
            "before_end_date": date(2024, 9, 5),
            "after_start_date": date(2024, 9, 14),
            "after_end_date": date(2024, 9, 25),
            "polarization": "VH",
            "orbit_pass": "BOTH",
            "threshold": 1.25,
            "scale": 20,
        }
    )
    assert warnings == []


def test_validate_analysis_parameters_reports_invalid_values():
    warnings = validate_analysis_parameters(
        {
            "before_start_date": date(2024, 9, 5),
            "before_end_date": date(2024, 8, 20),
            "after_start_date": date(2024, 9, 25),
            "after_end_date": date(2024, 9, 14),
            "polarization": "HH",
            "orbit_pass": "SIDEWAYS",
            "threshold": 0,
            "scale": 15,
        }
    )
    assert len(warnings) == 6

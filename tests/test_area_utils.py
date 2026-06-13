import pytest

from src.utils.area_utils import (
    dominant_class,
    hectares_to_square_kilometers,
    square_meters_to_square_kilometers,
    sum_selected_classes,
)


def test_square_meters_to_square_kilometers():
    assert square_meters_to_square_kilometers(1_250_000) == 1.25
    assert square_meters_to_square_kilometers(None) == 0.0


def test_hectares_to_square_kilometers():
    assert hectares_to_square_kilometers(250) == 2.5


def test_negative_area_rejected():
    with pytest.raises(ValueError):
        square_meters_to_square_kilometers(-1)


def test_dominant_class_and_selected_sum():
    stats = {"crops": 2.0, "built": 0.5, "trees": 3.25}
    assert dominant_class(stats) == "trees"
    assert sum_selected_classes(stats, ["crops", "built"]) == 2.5

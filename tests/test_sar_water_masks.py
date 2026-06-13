from src.gee.sar_water_masks import (
    overlap_percent,
    sar_dynamic_world_overlap,
    sar_water_change_masks,
    sar_water_area_metrics,
    sar_water_mask,
    sar_water_threshold_for_mode,
)


class FakeMask:
    def __init__(self, expression):
        self.expression = expression

    def lt(self, threshold):
        return FakeMask(f"lt({self.expression},{threshold})")

    def eq(self, value):
        value_expression = getattr(value, "expression", value)
        return FakeMask(f"eq({self.expression},{value_expression})")

    def neq(self, value):
        value_expression = getattr(value, "expression", value)
        return FakeMask(f"neq({self.expression},{value_expression})")

    def And(self, other):
        return FakeMask(f"and({self.expression},{other.expression})")

    def Not(self):
        return FakeMask(f"not({self.expression})")

    def selfMask(self):
        return FakeMask(f"selfMask({self.expression})")

    def clip(self, aoi):
        return FakeMask(f"clip({self.expression},{aoi})")

    def unmask(self, value):
        return FakeMask(f"unmask({self.expression},{value})")

    def connectedPixelCount(self, size, eight_connected):
        return FakeMask(f"connected({self.expression},{size},{eight_connected})")

    def gte(self, value):
        return FakeMask(f"gte({self.expression},{value})")

    def updateMask(self, mask):
        return FakeMask(f"updateMask({self.expression},{mask.expression})")


def test_sar_water_threshold_modes_vh():
    assert sar_water_threshold_for_mode("VH", "Conservator", -99) == -20.0
    assert sar_water_threshold_for_mode("VH", "Echilibrat", -99) == -18.0
    assert sar_water_threshold_for_mode("VH", "Sensibil", -99) == -16.0


def test_sar_water_threshold_modes_vv():
    assert sar_water_threshold_for_mode("VV", "Conservator", -99) == -17.0
    assert sar_water_threshold_for_mode("VV", "Echilibrat", -99) == -15.0
    assert sar_water_threshold_for_mode("VV", "Sensibil", -99) == -13.0


def test_sar_water_manual_threshold():
    assert sar_water_threshold_for_mode("VH", "Manual", -18.5) == -18.5


def test_overlap_percent_handles_zero():
    assert overlap_percent(2.0, 0.0) == 0.0
    assert overlap_percent(2.0, 8.0) == 25.0


def test_sar_water_mask_thresholds_and_clips_to_aoi():
    result = sar_water_mask(FakeMask("sar"), -18.0, "county", 0)
    assert result.expression == "clip(selfMask(lt(sar,-18.0)),county)"


def test_sar_water_mask_applies_connected_pixel_filter():
    result = sar_water_mask(FakeMask("sar"), -18.0, "county", 8)
    assert "connected(clip(selfMask(lt(sar,-18.0)),county),100,True)" in result.expression
    assert result.expression.startswith("clip(selfMask(updateMask(")


def test_sar_water_change_masks_build_new_persistent_and_loss():
    masks = sar_water_change_masks(FakeMask("before"), FakeMask("after"), "county")
    assert masks["sar_new_water"].expression == (
        "clip(selfMask(and(unmask(after,0),not(unmask(before,0)))),county)"
    )
    assert masks["sar_persistent_water"].expression == (
        "clip(selfMask(and(unmask(after,0),unmask(before,0))),county)"
    )
    assert masks["sar_water_loss"].expression == (
        "clip(selfMask(and(unmask(before,0),not(unmask(after,0)))),county)"
    )


def test_sar_dynamic_world_overlap_builds_overlap_and_only_layers():
    masks = sar_dynamic_world_overlap(FakeMask("sar_new"), FakeMask("dw_new"), "county")
    assert masks["sar_dynamic_world_new_water_overlap"].expression == (
        "clip(selfMask(and(unmask(sar_new,0),unmask(dw_new,0))),county)"
    )
    assert masks["new_water_only_sar"].expression == (
        "clip(selfMask(and(unmask(sar_new,0),not(unmask(dw_new,0)))),county)"
    )
    assert masks["new_water_only_dynamic_world"].expression == (
        "clip(selfMask(and(unmask(dw_new,0),not(unmask(sar_new,0)))),county)"
    )


def test_area_metrics_use_one_multiband_reduce_region_call():
    calls = []

    class AreaImage:
        def divide(self, value):
            return self

        def updateMask(self, mask):
            return self

        def rename(self, name):
            return self

        def addBands(self, other):
            return self

        def reduceRegion(self, **kwargs):
            calls.append(kwargs)

            class Result:
                def getInfo(self):
                    return {
                        "sar_water_before_area_km2": 1,
                        "sar_water_after_area_km2": 2,
                        "sar_new_water_area_km2": 1,
                    }

            return Result()

    class ImageFactory:
        @staticmethod
        def pixelArea():
            return AreaImage()

    class ReducerFactory:
        @staticmethod
        def sum():
            return "sum"

    class FakeEE:
        Image = ImageFactory
        Reducer = ReducerFactory

    values = sar_water_area_metrics(
        FakeEE(),
        {
            "sar_water_before": object(),
            "sar_water_after": object(),
            "sar_new_water": object(),
        },
        "aoi",
        10,
    )

    assert len(calls) == 1
    assert calls[0]["bestEffort"] is False
    assert values["sar_new_water_area_km2"] == 1.0

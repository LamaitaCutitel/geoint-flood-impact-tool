from src.gee.dynamic_world import dynamic_world_water_change_masks

from tests.test_sar_water_masks import FakeMask


def test_dynamic_world_water_change_masks_builds_expected_layers():
    masks = dynamic_world_water_change_masks(
        FakeMask("before"), FakeMask("after"), FakeMask("flood"), "county"
    )
    assert masks["dynamic_world_new_water"].expression == (
        "clip(selfMask(and(eq(after,0),neq(before,0))),county)"
    )
    assert masks["dynamic_world_water_loss"].expression == (
        "clip(selfMask(and(eq(before,0),neq(after,0))),county)"
    )
    assert masks["dynamic_world_other_change"].expression == (
        "clip(selfMask(and(and(neq(before,after),not(and(eq(after,0),neq(before,0)))),"
        "not(and(eq(before,0),neq(after,0))))),county)"
    )

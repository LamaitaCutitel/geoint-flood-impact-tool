from __future__ import annotations

from src.impact_tool.models import ImpactToolState
from src.impact_tool.state import apply_scene_pair


def _scene(scene_id: str) -> dict[str, str]:
    return {"ee_id": scene_id}


def test_scene_change_invalidates_results_report_and_comparators() -> None:
    state = ImpactToolState(
        before_scene=_scene("old-before"),
        after_scene=_scene("old-after"),
        scenes_confirmed=True,
        analysis_complete=True,
        analysis_results={"sar": {"ready": True}},
        report_bytes=b"pdf",
        report_filename="old.pdf",
        scene_compare_active=True,
        scene_compare_tiles={"before": "a", "after": "b"},
        layer_compare_active=True,
    )

    apply_scene_pair(state, _scene("new-before"), _scene("new-after"), False)

    assert state.analysis_complete is False
    assert state.analysis_results == {}
    assert state.report_bytes is None
    assert state.report_filename == ""
    assert state.scenes_confirmed is False
    assert state.scene_compare_active is False
    assert state.layer_compare_active is False
    assert state.comparison_ready is True


def test_confirmed_pair_disables_scene_comparator() -> None:
    state = ImpactToolState()

    apply_scene_pair(state, _scene("before"), _scene("after"), False)
    state.scene_compare_active = True
    state.scene_compare_tiles = {"before": "a", "after": "b"}
    apply_scene_pair(state, _scene("before"), _scene("after"), True)

    assert state.scenes_confirmed is True
    assert state.comparison_ready is False
    assert state.scene_compare_active is False
    assert state.scene_compare_tiles == {}

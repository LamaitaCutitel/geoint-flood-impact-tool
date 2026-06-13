from __future__ import annotations

import io
import json
import os
import time

from src.impact_tool.cache import PersistentCache
from src.impact_tool.scenes import (
    THUMBNAIL_TTL_SECONDS,
    confirm_scene_pair,
    hydrate_scene_thumbnails,
    search_scenes,
    select_scene_pair,
    timeline_entries,
)


def _scene(scene_id: str, timestamp: str, orbit: int = 80) -> dict:
    return {
        "ee_id": scene_id,
        "display_id": scene_id,
        "acquisition_time": timestamp,
        "polarization": "VH",
        "orbit_pass": "ASCENDING",
        "relative_orbit": orbit,
        "instrument_mode": "IW",
        "coverage_percent": 100,
    }


def test_scene_search_cache(tmp_path) -> None:
    calls = []

    def searcher(*args):
        calls.append(args)
        return {"scenes": [_scene("a", "2024-01-01T00:00:00Z")], "warnings": [], "errors": []}

    cache = PersistentCache(tmp_path)
    first = search_scenes(
        cache=cache,
        aoi_hash="area",
        start_date="2024-01-01",
        end_date="2024-02-01",
        polarization="VH",
        orbit_pass="ASCENDING",
        searcher=searcher,
    )
    second = search_scenes(
        cache=cache,
        aoi_hash="area",
        start_date="2024-01-01",
        end_date="2024-02-01",
        polarization="VH",
        orbit_pass="ASCENDING",
        searcher=searcher,
    )
    assert not first.from_cache
    assert second.from_cache
    assert len(calls) == 1


def test_zero_scenes_and_error_are_preserved(tmp_path) -> None:
    result = search_scenes(
        cache=PersistentCache(tmp_path),
        aoi_hash="area",
        start_date="2024-01-01",
        end_date="2024-02-01",
        polarization="VH",
        orbit_pass="BOTH",
        searcher=lambda *args: {
            "scenes": [],
            "warnings": ["Nicio scenă"],
            "errors": [{"message": "GEE indisponibil"}],
        },
    )
    assert result.scenes == []
    assert result.warnings == ["Nicio scenă"]
    assert result.errors == ["GEE indisponibil"]


def test_selection_and_confirmation() -> None:
    scenes = [
        _scene("before", "2024-01-01T00:00:00Z"),
        _scene("after", "2024-01-13T00:00:00Z"),
    ]
    before, after = select_scene_pair(scenes, "before", "after")
    result = confirm_scene_pair(before, after)
    assert result["confirmed"]


def test_incompatible_pair_is_blocked() -> None:
    before = _scene("before", "2024-01-13T00:00:00Z")
    after = _scene("after", "2024-01-01T00:00:00Z")
    assert not confirm_scene_pair(before, after)["confirmed"]


def test_relative_orbit_warning_requires_acceptance() -> None:
    before = _scene("before", "2024-01-01T00:00:00Z", 80)
    after = _scene("after", "2024-01-13T00:00:00Z", 81)
    assert not confirm_scene_pair(before, after)["confirmed"]
    assert not confirm_scene_pair(
        before,
        after,
        warnings_accepted=True,
    )["confirmed"]
    assert confirm_scene_pair(
        before,
        after,
        warnings_accepted=True,
        allow_relative_orbit_override=True,
    )["confirmed"]


def test_low_coverage_warns_and_requires_explicit_override() -> None:
    before = _scene("before", "2024-01-01T00:00:00Z")
    after = _scene("after", "2024-01-13T00:00:00Z")
    after["coverage_percent"] = 93

    blocked = confirm_scene_pair(before, after)
    overridden = confirm_scene_pair(
        before,
        after,
        warnings_accepted=True,
        allow_low_coverage_override=True,
    )

    assert blocked["confirmed"] is False
    assert any("95%" in message for message in blocked["warnings"])
    assert overridden["confirmed"] is True
    assert overridden["overrides"]["low_coverage"] is True


def test_swipe_has_single_control_and_fallback() -> None:
    from src.impact_tool.map.builder import build_shell_map

    html = build_shell_map(None, "Galati", preview_tiles={"before": "a", "after": "b"}).get_root().render()
    assert html.count("map.createPane('impactSwipeBefore')") == 1
    assert "L.control.sideBySide(" not in html
    assert "type = 'range'" not in html


class FakeThumbnailImage:
    def getThumbURL(self, params):
        return "https://example.test/thumbnail.png"


def test_thumbnail_cache_hit_and_miss(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.impact_tool.scenes.selected_scene_image",
        lambda *args: FakeThumbnailImage(),
    )
    monkeypatch.setattr(
        "src.impact_tool.scenes.urlopen",
        lambda *args, **kwargs: io.BytesIO(b"png"),
    )
    cache = PersistentCache(tmp_path)
    scenes = [_scene("scene", "2024-01-01T00:00:00Z")]
    first, first_hits = hydrate_scene_thumbnails(
        cache=cache,
        ee=object(),
        aoi=object(),
        aoi_hash="area",
        scenes=scenes,
    )
    second, second_hits = hydrate_scene_thumbnails(
        cache=cache,
        ee=object(),
        aoi=object(),
        aoi_hash="area",
        scenes=scenes,
    )
    assert first[0]["thumbnail_url"].endswith(".png")
    assert os.path.exists(first[0]["thumbnail_url"])
    assert first_hits == 0
    assert second_hits == 1


def test_thumbnail_cache_regenerates_expired_or_missing_file(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "src.impact_tool.scenes.selected_scene_image",
        lambda *args: FakeThumbnailImage(),
    )

    def fake_open(*args, **kwargs):
        calls.append(args)
        return io.BytesIO(b"png")

    monkeypatch.setattr("src.impact_tool.scenes.urlopen", fake_open)
    cache = PersistentCache(tmp_path)
    scenes = [_scene("scene", "2024-01-01T00:00:00Z")]
    first, _ = hydrate_scene_thumbnails(
        cache=cache,
        ee=object(),
        aoi=object(),
        aoi_hash="area",
        scenes=scenes,
    )
    os.unlink(first[0]["thumbnail_url"])
    hydrate_scene_thumbnails(
        cache=cache,
        ee=object(),
        aoi=object(),
        aoi_hash="area",
        scenes=scenes,
    )
    metadata_file = next((tmp_path / "thumbnails").glob("*.json"))
    envelope = json.loads(metadata_file.read_text(encoding="utf-8"))
    envelope["created_at"] = time.time() - THUMBNAIL_TTL_SECONDS - 1
    metadata_file.write_text(json.dumps(envelope), encoding="utf-8")
    hydrate_scene_thumbnails(
        cache=cache,
        ee=object(),
        aoi=object(),
        aoi_hash="area",
        scenes=scenes,
    )
    assert len(calls) == 3


def test_only_first_thumbnail_batch_is_generated(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "src.impact_tool.scenes.selected_scene_image",
        lambda *args: calls.append(args) or FakeThumbnailImage(),
    )
    monkeypatch.setattr(
        "src.impact_tool.scenes.urlopen",
        lambda *args, **kwargs: io.BytesIO(b"png"),
    )
    scenes = [
        _scene(str(index), f"2024-01-{index + 1:02d}T00:00:00Z")
        for index in range(10)
    ]
    hydrated, _ = hydrate_scene_thumbnails(
        cache=PersistentCache(tmp_path),
        ee=object(),
        aoi=object(),
        aoi_hash="area",
        scenes=scenes,
    )
    assert len(calls) == 8
    assert hydrated[8]["thumbnail_url"] is None


def test_timeline_is_chronological() -> None:
    entries = timeline_entries(
        [
            _scene("later", "2024-01-13T00:00:00Z"),
            _scene("earlier", "2024-01-01T00:00:00Z"),
        ]
    )
    assert [entry["scene_id"] for entry in entries] == ["earlier", "later"]


def test_single_scene_preview_layer() -> None:
    from src.impact_tool.map.builder import build_shell_map

    html = build_shell_map(
        None,
        "Galati",
        preview_scene_tile="https://tiles/preview/{z}/{x}/{y}",
    ).get_root().render()
    assert html.count("https://tiles/preview/{z}/{x}/{y}") == 1


def test_compare_action_precedes_confirmation() -> None:
    from pathlib import Path

    source = Path("src/impact_tool/ui/sidebar.py").read_text(encoding="utf-8")
    assert source.index('"Compară imaginile"') < source.index('"Confirmă imaginile"')
    assert '"Ieși din comparație"' in source
    assert '"Curăță selecția"' in source
    assert "Activează bara BEFORE / AFTER" not in source
    compare_block = source.split('"Compară imaginile"', 1)[1].split(
        '"Confirmă imaginile"',
        1,
    )[0]
    assert "state.scene_compare_active = True" in compare_block
    advanced_block = source.split(
        'st.expander("Opțiuni avansate"',
        1,
    )[1].split("if state.comparison_ready:", 1)[0]
    assert '"Mod comparație"' in advanced_block
    assert source.count('"Rulează analiza completă"') == 1


def test_large_scene_explorer_is_outside_sidebar_and_uses_four_columns() -> None:
    from pathlib import Path

    sidebar = Path("src/impact_tool/ui/sidebar.py").read_text(encoding="utf-8")
    shell = Path("src/impact_tool/ui/shell.py").read_text(encoding="utf-8")
    assert "def render_scene_explorer" in sidebar
    assert "render_scene_explorer(st, state)" in shell
    assert "st.columns(4)" in sidebar
    assert "Previzualizează pe hartă" in sidebar
    assert "Scena curentă" in sidebar
    assert "Perechea BEFORE / AFTER" in sidebar

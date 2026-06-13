from __future__ import annotations

import json
import time

from src.impact_tool.cache import (
    CACHE_ROOT,
    PersistentCache,
    invalidation_namespaces,
    scene_cache_key,
)


def test_default_cache_root_is_absolute() -> None:
    assert CACHE_ROOT.is_absolute()
    assert PersistentCache().root == CACHE_ROOT
from src.impact_tool.models import ImpactToolState
from src.impact_tool.state import update_buffer


def test_cache_miss_and_hit(tmp_path) -> None:
    cache = PersistentCache(tmp_path)
    assert not cache.get("scenes", "missing").hit
    cache.set("scenes", "known", {"count": 2})
    result = cache.get("scenes", "known")
    assert result.hit
    assert result.value == {"count": 2}


def test_cache_ttl(tmp_path) -> None:
    cache = PersistentCache(tmp_path)
    path = cache.set("osm", "buildings", [1])
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["created_at"] = time.time() - 100
    path.write_text(json.dumps(envelope), encoding="utf-8")
    result = cache.get("osm", "buildings", ttl_seconds=10)
    assert not result.hit
    assert result.expired


def test_cache_keys_are_stable(tmp_path) -> None:
    cache = PersistentCache(tmp_path)
    key_a = scene_cache_key(cache, "aoi", ("2024-01-01", "2024-02-01"), "VV", "ASCENDING")
    key_b = scene_cache_key(cache, "aoi", ("2024-01-01", "2024-02-01"), "VV", "ASCENDING")
    assert key_a == key_b


def test_selective_invalidation_contract() -> None:
    assert "scenes" in invalidation_namespaces("aoi")
    assert "tiles" in invalidation_namespaces("scenes")
    assert invalidation_namespaces("buffer") == ("statistics", "reports")


def test_buffer_change_keeps_raster_results() -> None:
    state = ImpactToolState(
        analysis_results={"sar": {"area": 2}, "dynamic_world": {"area": 1}, "osm_impact": {}},
        report_bytes=b"pdf",
    )
    assert update_buffer(state, 300)
    assert state.analysis_results["sar"] == {"area": 2}
    assert state.analysis_results["dynamic_world"] == {"area": 1}
    assert "osm_impact" not in state.analysis_results
    assert state.report_bytes is None


def test_cache_directory_is_ignored() -> None:
    gitignore = open(".gitignore", encoding="utf-8").read().splitlines()
    assert "cache/" in gitignore

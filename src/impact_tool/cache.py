from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = Path(os.environ.get("GEOINT_CACHE_DIR", PROJECT_ROOT / "cache")).resolve()


@dataclass(frozen=True)
class CacheResult:
    value: Any
    hit: bool
    expired: bool = False


class PersistentCache:
    def __init__(self, root: Path | str = CACHE_ROOT) -> None:
        self.root = Path(root).expanduser().resolve()

    def key(self, namespace: str, *parts: Any) -> str:
        payload = json.dumps(parts, ensure_ascii=True, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        return f"{namespace}-{digest}"

    def get(self, namespace: str, key: str, ttl_seconds: int | None = None) -> CacheResult:
        path = self._path(namespace, key)
        if not path.exists():
            return CacheResult(None, False)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return CacheResult(None, False)
        age = time.time() - float(envelope.get("created_at", 0))
        if ttl_seconds is not None and age > ttl_seconds:
            return CacheResult(None, False, expired=True)
        return CacheResult(envelope.get("value"), True)

    def set(self, namespace: str, key: str, value: Any) -> Path:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"created_at": time.time(), "value": value}
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return path

    def invalidate_namespace(self, namespace: str) -> int:
        directory = self.root / namespace
        if not directory.exists():
            return 0
        removed = 0
        for path in directory.glob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def namespaces(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(path.name for path in self.root.iterdir() if path.is_dir())

    def _path(self, namespace: str, key: str) -> Path:
        safe_key = "".join(character for character in key if character.isalnum() or character in "-_")
        return self.root / namespace / f"{safe_key}.json"


def scene_cache_key(
    cache: PersistentCache,
    aoi_hash: str,
    temporal_interval: tuple[str, str],
    polarization: str,
    orbit_pass: str,
) -> str:
    return cache.key("scenes", aoi_hash, temporal_interval, polarization, orbit_pass)


def tile_cache_key(
    cache: PersistentCache,
    aoi_hash: str,
    before_id: str,
    after_id: str,
    layer_id: str,
    parameters: dict[str, Any],
) -> str:
    return cache.key("tiles", aoi_hash, before_id, after_id, layer_id, parameters)


def analysis_hash(aoi_hash: str, before_id: str, after_id: str, parameters: dict[str, Any]) -> str:
    payload = json.dumps(
        [aoi_hash, before_id, after_id, parameters],
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def invalidation_namespaces(change: str) -> tuple[str, ...]:
    mapping = {
        "aoi": ("scenes", "tiles", "dynamic_world", "osm", "statistics", "reports"),
        "scenes": ("tiles", "dynamic_world", "statistics", "reports"),
        "buffer": ("statistics", "reports"),
    }
    return mapping.get(change, ())

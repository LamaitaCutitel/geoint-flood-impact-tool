import sys
from pathlib import Path

from src.gee.gee_auth import has_local_earthengine_credentials, initialize_earth_engine
from src.gee.sentinel1_collection import count_scenes


def test_initialize_earth_engine_without_project_id(monkeypatch):
    monkeypatch.setenv("GEE_PROJECT_ID", "")
    result = initialize_earth_engine(interactive=False)
    assert result.available is False
    assert "GEE_PROJECT_ID" in result.message


def test_initialize_earth_engine_without_package(monkeypatch):
    monkeypatch.setenv("GEE_PROJECT_ID", "demo-project")
    monkeypatch.setitem(sys.modules, "ee", None)
    result = initialize_earth_engine(interactive=False)
    assert result.available is False
    assert "earthengine-api" in result.message


def test_local_credentials_permission_error_counts_as_present(monkeypatch):
    class _BlockedPath:
        def __truediv__(self, _):
            return self

        def exists(self):
            raise PermissionError("blocked")

    monkeypatch.setattr(Path, "home", lambda: _BlockedPath())
    assert has_local_earthengine_credentials() is True


class _BrokenCollection:
    def size(self):
        raise RuntimeError("No scenes")


def test_count_scenes_fallback_for_missing_sentinel1_scenes():
    assert count_scenes(_BrokenCollection()) == 0

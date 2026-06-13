# Architecture

`impact_tool.py` is the only application entrypoint.

- `src/impact_tool/`: workflow, state, analysis orchestration, map, UI, and report generation.
- `src/gee/`: server-side Google Earth Engine operations for Sentinel-1 SAR and Dynamic World.
- `src/app_support/`: small reusable county, styling, and geometry helpers.
- `config/`: environment-backed configuration without secrets.
- `tests/`: offline unit, integration, UI shell, and smoke tests.

Raster processing remains in Google Earth Engine. The local application handles orchestration, compact vector results, presentation, and report generation.

# GEOINT Flood Impact Tool

Streamlit application for a reproducible, preliminary GEOINT assessment of newly observed water and potentially exposed elements.

The application identifies preliminary new water observed through Sentinel-1 SAR
using a strict BEFORE / AFTER comparison. JRC and DEM are not used.

## Workflow

1. Select a county or draw an optional AOI.
2. Search and select compatible Sentinel-1 BEFORE and AFTER scenes.
3. Compare the scenes with the vertical map divider and confirm the pair.
4. Run the complete analysis.
5. Inspect the Leaflet layers, concise impact summary, exposed elements and technical details.
6. Generate the preliminary PDF report.

The complete analysis keeps SAR as the authoritative required stage. Dynamic World,
Geoapify and targeted Overpass data are optional: a temporary external-service
failure is reported without discarding available raster results.

Map visibility is controlled directly by the Leaflet layer panel. Toggling a layer
does not rerun Streamlit or reset the current map view. Drawing an AOI requests one
fit to that geometry; normal layer changes, popups, pan and zoom preserve the view.
Reference buildings remain opt-in and are recommended at zoom 14 or greater.

OSM retrieval is limited to significant components of `SAR new water + warning
buffer`. Important facilities cover the active county or AOI, including unexposed
context markers, and use Overpass as a fallback when Geoapify Places is unavailable.

## Local setup

```powershell
.\scripts\start_app.ps1
```

The script creates a Python 3.12 virtual environment, installs `requirements.txt`, checks the local Google Earth Engine configuration, and starts `impact_tool.py`.

## Validation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_local_run.ps1
```

The product is a preliminary decision-support output. It does not confirm flooding in the field.

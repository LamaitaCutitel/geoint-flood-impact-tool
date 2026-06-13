# GEOINT Flood Impact Tool

Streamlit application for a reproducible, preliminary GEOINT assessment of newly observed water and potentially exposed elements.

The application identifies preliminary new water observed through Sentinel-1 SAR
using a strict BEFORE / AFTER comparison. JRC and DEM are not used.

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

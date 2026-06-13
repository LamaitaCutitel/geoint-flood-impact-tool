# Local Run

## Requirements

- Windows PowerShell
- Python 3.12
- Google Earth Engine account authorized locally

## Start

```powershell
.\scripts\start_app.ps1
```

If PowerShell blocks local scripts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_app.ps1
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_local_run.ps1
```

Local secrets belong in `.env`, which is ignored. Start from `.env.example`.

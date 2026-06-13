param(
    [int]$Port = 8501,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot

if (-not (Test-Path ".env")) {
    Write-Warning ".env lipseste. Copiaza .env.example si seteaza GEE_PROJECT_ID local."
}

$venvPath = ".venv"
if (-not (Test-Path "$venvPath\Scripts\python.exe")) {
    Write-Host "Creez mediul virtual Python 3.12 in .venv..."
    py -3.12 -m venv .venv
}

$python = Join-Path $venvPath "Scripts\python.exe"
. (Join-Path $venvPath "Scripts\Activate.ps1")
& $python -c "import sys; assert sys.version_info[:2] == (3, 12), 'Este necesar Python 3.12'; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Versiunea Python nu este compatibila." }

if (-not $SkipInstall) {
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Actualizarea pip a esuat." }
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Instalarea requirements.txt a esuat." }
}

Write-Host "Verific initializarea Google Earth Engine..."
& $python -c "from src.gee.gee_auth import local_earthengine_status; s=local_earthengine_status(); print(s.message)"
if ($LASTEXITCODE -ne 0) { throw "Verificarea Google Earth Engine a esuat." }

Write-Host "Pornesc tool-ul la http://127.0.0.1:$Port"
& $python -m streamlit run impact_tool.py --server.address 127.0.0.1 --server.port $Port

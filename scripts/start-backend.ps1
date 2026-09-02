# Start the RecoverOS API on Windows without Make.
#
# Paths are relative to this script, so the repo works from any directory and
# for anyone who clones it — the earlier version hard-coded one machine's
# absolute path.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:PYTHONPATH = "backend"

# Prefer the local virtualenv if one exists, otherwise whatever python is on PATH.
$python = if (Test-Path ".\venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" } else { "python" }

Write-Host "RecoverOS API  ->  http://localhost:8000/docs" -ForegroundColor Cyan
& $python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

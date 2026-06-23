# Build the Lore sidecar into a standalone binary with PyInstaller.
#
# Usage (from the sidecar/ directory):
#   ./build.ps1
#
# Produces dist/lore-sidecar/ — a folder with lore-sidecar.exe and its bundled
# libraries. The Tauri build (npm run tauri build) picks this up via
# tauri.conf.json's bundle.resources and ships it inside the installer, so end
# users need no Python.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment…"
    python -m venv .venv
}

Write-Host "Installing dependencies…"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-dev.txt

Write-Host "Freezing the sidecar…"
& $python -m PyInstaller --noconfirm --clean lore-sidecar.spec

Write-Host "Done. Output: dist/lore-sidecar/lore-sidecar.exe"

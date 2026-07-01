# Build the standalone Sector executable (ONEDIR) into dist/Sector.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1
#
# Produces dist/Sector/Sector.exe with its _internal dependency folder. Zip the
# whole dist/Sector folder to distribute it.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root

Write-Host "Installing build dependencies..."
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet "pyinstaller>=6,<7"

Write-Host "Building (this can take a few minutes)..."
python -m PyInstaller --noconfirm --clean packaging/sector.spec

Write-Host "Done. Run dist/Sector/Sector.exe"

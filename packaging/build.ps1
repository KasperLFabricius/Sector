# Build an unsigned Sector QA package (ONEDIR) into dist/Sector.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1
#
# The result is for static QA inspection only. It must not be launched, zipped
# or distributed. A distributable Sector build requires the separately
# authorised signing workflow.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root

Write-Warning "UNSIGNED QA PACKAGE ONLY. Do not launch, zip or distribute this artifact."

Write-Host "Installing locked build dependencies..."
python -m pip install --quiet --require-hashes -r requirements-build.txt

Write-Host "Generating third-party notices..."
python tools/generate_third_party_notices.py `
  --output build/legal/THIRD_PARTY_NOTICES.txt

Write-Host "Building (this can take a few minutes)..."
python -m PyInstaller --noconfirm --clean packaging/sector.spec

Copy-Item -LiteralPath LICENSE -Destination dist/Sector/LICENSE.txt -Force
Copy-Item -LiteralPath build/legal/THIRD_PARTY_NOTICES.txt `
  -Destination dist/Sector/THIRD_PARTY_NOTICES.txt -Force

Write-Host "Unsigned QA build complete at dist/Sector."
Write-Host "Inspection only: do not launch, zip or distribute this artifact."
